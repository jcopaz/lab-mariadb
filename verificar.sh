#!/usr/bin/env bash
#
# verificar.sh — Laboratório MariaDB (VARCHAR vs. tipos adequados)
# IFSP Campus Guarulhos — Arquitetura de Computadores
#
# Roda os comandos de verificação do laboratório (Seções 6 e 7) e imprime
# tudo formatado, pronto para copiar e colar na atividade do AVA.
# NÃO apaga nem insere dados — só consulta e mede o que já existe.
#
# Uso:
#   ./verificar.sh -p SUASENHA
#   ./verificar.sh -u sysadmin -p SUASENHA -d exemplo01
#   ./verificar.sh -p SUASENHA -f 1.65      # também tenta localizar o
#                                            # padrão IEEE-754 de 1.65 no .ibd
#
# Requer: cliente mysql, sudo (para ler /var/lib/mysql e os .ibd), python3
# (só necessário se usar -f), strings, hexdump.

set -euo pipefail

HOST="127.0.0.1"
USER="sysadmin"
PASSWORD=""
DATABASE="exemplo01"
VALOR_FLOAT=""

uso() {
  echo "Uso: $0 -p SENHA [-u USUARIO] [-h HOST] [-d BANCO] [-f VALOR_FLOAT]"
  echo "  -p  senha do usuário MariaDB (obrigatório)"
  echo "  -u  usuário MariaDB (padrão: sysadmin)"
  echo "  -h  host do MariaDB (padrão: 127.0.0.1)"
  echo "  -d  banco de dados (padrão: exemplo01)"
  echo "  -f  valor float para localizar o padrão IEEE-754 no .ibd (opcional)"
  exit 1
}

while getopts "u:p:h:d:f:" opt; do
  case "$opt" in
    u) USER="$OPTARG" ;;
    p) PASSWORD="$OPTARG" ;;
    h) HOST="$OPTARG" ;;
    d) DATABASE="$OPTARG" ;;
    f) VALOR_FLOAT="$OPTARG" ;;
    *) uso ;;
  esac
done

if [ -z "$PASSWORD" ]; then
  echo "Erro: a senha é obrigatória (-p SENHA)."
  uso
fi

MYSQL_CMD=(mysql -h "$HOST" -u "$USER" -p"$PASSWORD" "$DATABASE")
DIR_BANCO="/var/lib/mysql/$DATABASE"
IBD_TIPADA="$DIR_BANCO/pessoas_tipada.ibd"
IBD_VARCHAR="$DIR_BANCO/pessoas_varchar.ibd"

separador() { printf '\n%s\n' "======================================================================"; }

separador
echo "[1] CONTAGEM DE REGISTROS E ESTATÍSTICAS LÓGICAS (information_schema)"
separador
"${MYSQL_CMD[@]}" -e "
SELECT COUNT(*) AS total_pessoas_varchar FROM pessoas_varchar;
SELECT COUNT(*) AS total_pessoas_tipada FROM pessoas_tipada;

ANALYZE TABLE pessoas_varchar, pessoas_tipada;
SELECT table_name, data_length AS bytes_dados, index_length AS bytes_indice,
       (data_length + index_length) AS total_bytes
FROM information_schema.tables
WHERE table_schema = '$DATABASE';
"

separador
echo "[2] TAMANHO FÍSICO DOS ARQUIVOS (ls -lh)"
separador
sudo ls -lh "$DIR_BANCO"/

separador
echo "[2b] TAMANHO FÍSICO EXATO EM BYTES (stat)"
separador
sudo stat --format="%n: %s bytes" "$IBD_VARCHAR" "$IBD_TIPADA" 2>/dev/null || \
  echo "Aviso: não consegui ler os arquivos .ibd. Rode este script com privilégios de leitura em $DIR_BANCO (ex.: sudo ./verificar.sh ...)."

separador
echo "[3] BUSCA POR TEXTO NO ARQUIVO BINÁRIO (strings -a)"
echo "    Mostrando as primeiras 10 linhas de texto encontradas em pessoas_tipada.ibd:"
separador
sudo strings -a "$IBD_TIPADA" 2>/dev/null | head -n 10 || \
  echo "Aviso: não consegui ler $IBD_TIPADA. Rode com privilégios adequados."

separador
echo "[4] MEDIDA LÓGICA DE CONTEÚDO BRUTO (sem overhead do InnoDB)"
separador
"${MYSQL_CMD[@]}" -e "
SELECT SUM(LENGTH(nome)+LENGTH(email)+LENGTH(cpf)+LENGTH(idade)+LENGTH(altura)+LENGTH(peso))
       AS bytes_conteudo_varchar
FROM pessoas_varchar;

SELECT SUM(LENGTH(nome)+LENGTH(email)+LENGTH(cpf)+LENGTH(idade)+LENGTH(altura)+LENGTH(peso))
       AS bytes_conteudo_tipada
FROM pessoas_tipada;
"

if [ -n "$VALOR_FLOAT" ]; then
  separador
  echo "[5] BUSCA DO PADRÃO IEEE-754 PARA O VALOR $VALOR_FLOAT"
  separador
  PADRAO=$(python3 -c "import struct; print(struct.pack('>f', $VALOR_FLOAT).hex())")
  echo "Padrão de bytes calculado (big-endian): $PADRAO"
  echo "Procurando no arquivo $IBD_TIPADA ..."
  if sudo hexdump -C "$IBD_TIPADA" 2>/dev/null | grep -i "$PADRAO"; then
    echo "==> Padrão ENCONTRADO."
  else
    echo "==> Padrão NÃO encontrado (resultado válido — ver Seção 7.3 do laboratório sobre por que isso pode acontecer)."
  fi
fi

separador
echo "Verificação concluída. Copie os blocos [1]-[5] acima para a atividade do AVA."
separador
