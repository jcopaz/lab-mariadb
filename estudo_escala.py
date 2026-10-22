#!/usr/bin/env python3
"""
Estudo de Escala — Laboratório MariaDB (VARCHAR vs. tipos adequados)
IFSP Campus Guarulhos — Arquitetura de Computadores

Automatiza o experimento em múltiplos volumes de dados (por padrão: 10 mil,
100 mil, 200 mil, 500 mil e 1 milhão de registros). Para cada volume, o
script:
  1. TRUNCA as tabelas pessoas_varchar e pessoas_tipada (apaga tudo!),
  2. gera e insere N registros idênticos em ambas,
  3. roda ANALYZE TABLE e consulta information_schema.tables (medida lógica),
  4. mede o tamanho físico real dos arquivos .ibd (medida física),
  5. registra tudo em uma tabela de resultados (impressa e salva em CSV).

ATENÇÃO — DESTRUTIVO: cada rodada apaga TODOS os dados das duas tabelas
antes de inserir o novo volume. Não use em tabelas com dados que você
queira preservar. Rode em ambiente de laboratório/teste.

ATENÇÃO — PERMISSÕES: a medição física (etapa 4) lê arquivos em
/var/lib/mysql/, que pertencem ao usuário `mysql`. Rode este script com
sudo para que a leitura funcione:
    sudo python3 estudo_escala.py --password SUASENHA

Sem sudo, a medição física falha silenciosamente (fica em branco no
resultado) — a medição lógica (information_schema) continua funcionando
normalmente, pois passa pela conexão MariaDB, não pelo sistema de arquivos.

Dependências:
    pip install pymysql Faker

Uso:
    sudo python3 estudo_escala.py --password SUASENHA

    # Volumes customizados:
    sudo python3 estudo_escala.py --password SUASENHA --volumes 10000,50000,100000

    # Reprodutível:
    sudo python3 estudo_escala.py --password SUASENHA --seed 42
"""

import argparse
import csv
import random
import subprocess
import sys
import time

try:
    import pymysql
except ImportError:
    sys.exit("Erro: instale a dependência com 'pip install pymysql'")

try:
    from faker import Faker
except ImportError:
    sys.exit("Erro: instale a dependência com 'pip install Faker'")


def gerar_cpf_numerico() -> str:
    """Gera 11 dígitos no formato de armazenamento do laboratório.
    Não valida dígitos verificadores reais."""
    return "".join(str(random.randint(0, 9)) for _ in range(11))


def gerar_registro(fake: Faker, indice: int) -> dict:
    """Gera um registro sintético. O e-mail é construído a partir do índice
    (não via fake.unique.email()) para garantir unicidade sem o custo de
    performance da checagem de unicidade do Faker em volumes grandes —
    essa checagem degrada muito e pode até falhar acima de algumas
    centenas de milhares de registros."""
    return {
        "nome": fake.name(),
        "email": f"pessoa{indice}@teste-lab.com",
        "cpf": gerar_cpf_numerico(),
        "idade": random.randint(1, 99),                    # cabe em TINYINT UNSIGNED (0-255)
        "altura": round(random.uniform(1.40, 2.10), 2),     # metros — cabe em FLOAT
        "peso": round(random.uniform(40.0, 150.0), 1),      # kg — cabe em FLOAT
    }


def truncar_tabelas(cursor):
    cursor.execute("TRUNCATE TABLE pessoas_varchar")
    cursor.execute("TRUNCATE TABLE pessoas_tipada")


def inserir_volume_streaming(cursor, fake: Faker, n: int, lote: int) -> None:
    """Gera e insere N registros em lotes de tamanho `lote`, sem nunca manter
    mais que um lote inteiro em memória ao mesmo tempo — o pico de memória
    fica limitado a `lote` registros, não ao volume total N (importante
    para os volumes de 500 mil e 1 milhão deste estudo)."""
    sql_varchar = (
        "INSERT INTO pessoas_varchar (nome, email, cpf, idade, altura, peso) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    sql_tipada = (
        "INSERT INTO pessoas_tipada (nome, email, cpf, idade, altura, peso) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    processados = 0
    indice_global = 0
    while processados < n:
        tamanho = min(lote, n - processados)
        lote_registros = [gerar_registro(fake, indice_global + i) for i in range(tamanho)]

        valores_varchar = [
            (r["nome"], r["email"], r["cpf"], str(r["idade"]), str(r["altura"]), str(r["peso"]))
            for r in lote_registros
        ]
        valores_tipada = [
            (r["nome"], r["email"], r["cpf"], r["idade"], r["altura"], r["peso"])
            for r in lote_registros
        ]
        cursor.executemany(sql_varchar, valores_varchar)
        cursor.executemany(sql_tipada, valores_tipada)

        processados += tamanho
        indice_global += tamanho
        if processados % (lote * 10) == 0 or processados == n:
            print(f"    {processados}/{n} registros inseridos...")


def medir_logico(cursor, database: str) -> dict:
    cursor.execute("ANALYZE TABLE pessoas_varchar, pessoas_tipada")
    cursor.fetchall()
    cursor.execute(
        "SELECT table_name, data_length, index_length "
        "FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name IN ('pessoas_varchar', 'pessoas_tipada')",
        (database,),
    )
    return {row[0]: {"data_length": row[1], "index_length": row[2]} for row in cursor.fetchall()}


def medir_fisico(database: str) -> dict:
    resultado = {}
    for tabela in ("pessoas_varchar", "pessoas_tipada"):
        caminho = f"/var/lib/mysql/{database}/{tabela}.ibd"
        try:
            saida = subprocess.run(
                ["stat", "--format=%s", caminho],
                capture_output=True, text=True, check=True,
            )
            resultado[tabela] = int(saida.stdout.strip())
        except Exception as e:
            print(f"    Aviso: não consegui medir {caminho} ({e}). "
                  f"Rode este script com sudo para medição física.")
            resultado[tabela] = None
    return resultado


def main():
    parser = argparse.ArgumentParser(description="Estudo de escala do laboratório MariaDB.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="sysadmin")
    parser.add_argument("--password", required=True)
    parser.add_argument("--database", default="exemplo01")
    parser.add_argument("--volumes", default="10000,100000,200000,500000,1000000",
                         help="Volumes a testar, separados por vírgula (padrão: 10000,100000,200000,500000,1000000)")
    parser.add_argument("--lote", type=int, default=2000,
                         help="Tamanho do lote para executemany (padrão: 2000)")
    parser.add_argument("--saida", default="estudo_escala_resultado.csv",
                         help="Arquivo CSV de saída (padrão: estudo_escala_resultado.csv)")
    parser.add_argument("--seed", type=int, default=None,
                         help="Seed para reprodutibilidade (opcional)")
    args = parser.parse_args()

    volumes = [int(v.strip()) for v in args.volumes.split(",")]

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)
    fake = Faker("pt_BR")

    conn = pymysql.connect(
        host=args.host, port=args.port, user=args.user,
        password=args.password, database=args.database, charset="utf8mb4",
    )

    linhas = []
    try:
        with conn.cursor() as cursor:
            for n in volumes:
                inicio = time.time()
                print(f"\n=== Rodando com {n} registros ===")

                print("  Truncando tabelas (apagando dados anteriores)...")
                truncar_tabelas(cursor)
                conn.commit()

                print(f"  Gerando e inserindo {n} registros (streaming, lotes de {args.lote})...")
                inserir_volume_streaming(cursor, fake, n, args.lote)
                conn.commit()

                print("  Medindo estatísticas lógicas (information_schema)...")
                logico = medir_logico(cursor, args.database)

                print("  Medindo tamanho físico dos arquivos .ibd...")
                fisico = medir_fisico(args.database)

                ibd_v = fisico["pessoas_varchar"]
                ibd_t = fisico["pessoas_tipada"]
                diferenca = (ibd_v - ibd_t) if (ibd_v is not None and ibd_t is not None) else None

                linha = {
                    "registros": n,
                    "data_length_varchar": logico["pessoas_varchar"]["data_length"],
                    "data_length_tipada": logico["pessoas_tipada"]["data_length"],
                    "ibd_bytes_varchar": ibd_v,
                    "ibd_bytes_tipada": ibd_t,
                    "diferenca_ibd_bytes": diferenca,
                }
                linhas.append(linha)

                elapsed = time.time() - inicio
                print(f"  data_length:  varchar={linha['data_length_varchar']:>12}   tipada={linha['data_length_tipada']:>12}")
                print(f"  .ibd físico:  varchar={str(ibd_v):>12}   tipada={str(ibd_t):>12}   diferença={str(diferenca)}")
                print(f"  (rodada concluída em {elapsed:.1f}s)")
    finally:
        conn.close()

    campos = ["registros", "data_length_varchar", "data_length_tipada",
              "ibd_bytes_varchar", "ibd_bytes_tipada", "diferenca_ibd_bytes"]
    with open(args.saida, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)

    print(f"\nResultados salvos em: {args.saida}")
    print("\nResumo final:")
    print(f"{'Registros':>10} | {'data_len VARCHAR':>17} | {'data_len TIPADA':>16} | {'.ibd VARCHAR':>13} | {'.ibd TIPADA':>12} | {'Diferença':>10}")
    print("-" * 90)
    for l in linhas:
        print(f"{l['registros']:>10} | {l['data_length_varchar']:>17} | {l['data_length_tipada']:>16} | "
              f"{str(l['ibd_bytes_varchar']):>13} | {str(l['ibd_bytes_tipada']):>12} | {str(l['diferenca_ibd_bytes']):>10}")


if __name__ == "__main__":
    main()
