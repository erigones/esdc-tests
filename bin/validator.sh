#!/bin/bash

usage() {
    echo "Usage ${0} <URL> [es_sessionid]"
    exit 1
}

URL="${1:-}"

[[ -z ${URL} ]] && usage

SHOW_IGNORED="${ES_VALIDATOR_SHOW_IGNORED:-"$3"}"
SESSIONID="${2:-"${ES_VALIDATOR_SESSIONID}"}"
TIMEOUT="${ES_VALIDATOR_TIMEOUT:-"5"}"
BASE_DIR="$(cd "$(dirname "$0")/.." ; pwd -P)"
BIN_DIR="${BASE_DIR}/bin"
VNU_JAR="${BIN_DIR}/vnu.jar"
IGNORE_FILE="${BASE_DIR}/validator/es_ignored_errors"
HTML_FILE=$(mktemp)

trap 'rm -f "${HTML_FILE}"' INT TERM EXIT

echo ">>> Downloading ${URL} ..." >&2
curl -m ${TIMEOUT} -v -k -s -f -k -b "es_sessionid=${SESSIONID}" "${URL}" -o "${HTML_FILE}"

if [[ ! -s "${HTML_FILE}" ]]; then
	echo "ERROR: Got empty response" >&2
	exit 3
fi

C_OFF='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_PURPLE='\033[0;35m'
C_CYAN='\033[0;36m'
C_WHITE='\033[0;37m'

i=0
err=0
es_err=0

echo >&2
echo ">>> Running validator ..." >&2
while read line; do
	((i++))
	if echo "${line}" | grep -f "${IGNORE_FILE}" -q > /dev/null; then
		((es_err++))
		[[ -z "${SHOW_IGNORED}" ]] && continue
		color=${C_YELLOW}
	else
		((err++))
		color=${C_RED}
	fi
	echo -e "${C_CYAN}[$i]${C_OFF} ${color}$(echo "${line}" | cut -d ':' -f 3-)${C_OFF}"
	lines="$(echo "${line}" | cut -d ':' -f 3)"
	begin="${lines%%.*}"
	_end="${lines##*-}"
	end="${_end%%.*}"
	sed -n ${begin},${end}p "${HTML_FILE}"
	echo "--"
done < <(java -jar "${VNU_JAR}" --errors-only --format gnu "${HTML_FILE}" 2>&1)

echo -e ">>> Found: ${C_WHITE}${i}${C_OFF} issue(s) Errors: ${C_RED}${err}${C_OFF} Ignored: ${C_YELLOW}${es_err}${C_OFF}" >&2
echo ">>> Done." >&2

exit ${err}
