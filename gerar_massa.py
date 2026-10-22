#!/usr/bin/env python3
"""
Gerador de massa de dados — Laboratório MariaDB (VARCHAR vs. tipos adequados)
IFSP Campus Guarulhos — Arquitetura de Computadores

Insere N registros idênticos em pessoas_varchar e pessoas_tipada. Este
script NÃO trunca as tabelas antes de inserir — cada execução SOMA
registros aos que já existem. Se quiser testar volumes isolados (do zero
a cada rodada), use estudo_escala.py em vez deste script.

Pré-requisitos no banco:
    As tabelas pessoas_varchar e pessoas_tipada já devem existir, com as
    colunas altura e peso incluídas desde a criação (ver roteiro do
    laboratório, Seções 2 e 3), ambas no mesmo banco de dados.

Dependências:
    pip install pymysql Faker

Uso:
    python3 gerar_massa.py --password SUASENHA --registros 10000

    # Reprodutível (mesma massa de dados sempre que rodar com a mesma seed):
    python3 gerar_massa.py --password SUASENHA --registros 10000 --seed 42
"""

import argparse
import random
import sys

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


def gerar_registro(fake: Faker) -> dict:
    """Gera um registro sintético. O e-mail usa um número aleatório em vez
    de fake.unique.email() — a checagem de unicidade do Faker degrada muito
    (fica lenta e pode até lançar UniquenessException) a partir de algumas
    centenas de milhares de registros, e a tabela não tem UNIQUE em email,
    então repetição ocasional de e-mail não afeta o experimento (o que
    importa é o tamanho em bytes do conteúdo, não a unicidade)."""
    return {
        "nome": fake.name(),
        "email": f"pessoa{random.randint(0, 999_999_999)}@teste-lab.com",
        "cpf": gerar_cpf_numerico(),
        "idade": random.randint(1, 99),                    # cabe em TINYINT UNSIGNED (0-255)
        "altura": round(random.uniform(1.40, 2.10), 2),     # metros — cabe em FLOAT
        "peso": round(random.uniform(40.0, 150.0), 1),      # kg — cabe em FLOAT
    }


def inserir_lote(cursor, tabela: str, registros: list, tipado: bool):
    """Insere UM lote (já do tamanho desejado) via executemany."""
    sql = (
        f"INSERT INTO {tabela} (nome, email, cpf, idade, altura, peso) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    if tipado:
        valores = [
            (r["nome"], r["email"], r["cpf"], r["idade"], r["altura"], r["peso"])
            for r in registros
        ]
    else:
        valores = [
            (r["nome"], r["email"], r["cpf"], str(r["idade"]), str(r["altura"]), str(r["peso"]))
            for r in registros
        ]
    cursor.executemany(sql, valores)


def main():
    parser = argparse.ArgumentParser(description="Gera massa de dados para o laboratório MariaDB.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", required=True)
    parser.add_argument("--database", default="exemplo01")
    parser.add_argument("--registros", type=int, default=10000,
                         help="Quantidade de registros a inserir em CADA tabela (padrão: 10000)")
    parser.add_argument("--lote", type=int, default=2000,
                         help="Tamanho do lote gerado e inserido por vez (padrão: 2000). "
                              "Reduza este valor se a máquina tiver pouca memória.")
    parser.add_argument("--seed", type=int, default=None,
                         help="Seed para reprodutibilidade (opcional)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    fake = Faker("pt_BR")

    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        charset="utf8mb4",
    )

    processados = 0
    try:
        with conn.cursor() as cursor:
            while processados < args.registros:
                tamanho = min(args.lote, args.registros - processados)
                # Gera e insere UM LOTE por vez — o pico de memória fica
                # limitado a --lote registros, não ao total de --registros.
                lote_registros = [gerar_registro(fake) for _ in range(tamanho)]

                inserir_lote(cursor, "pessoas_varchar", lote_registros, tipado=False)
                inserir_lote(cursor, "pessoas_tipada", lote_registros, tipado=True)
                conn.commit()

                processados += tamanho
                print(f"  {processados}/{args.registros} registros inseridos...")

        print("\nConcluído. Antes de consultar information_schema.tables, rode:")
        print("  ANALYZE TABLE pessoas_varchar, pessoas_tipada;\n")
        print("Depois compare:")
        print("  SELECT table_name, data_length, index_length, (data_length+index_length) AS total_bytes")
        print("  FROM information_schema.tables WHERE table_schema = 'exemplo01';\n")
        print("E o tamanho físico dos arquivos (após um FLUSH TABLES, se necessário):")
        print("  sudo ls -lh /var/lib/mysql/exemplo01/")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
