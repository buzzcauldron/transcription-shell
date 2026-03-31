#!/usr/bin/env bash
# Clone ideasrule/latin_documents for training data (data/*.jpg + *.xml).
# Usage:
#   ./scripts/clone-latin-documents.sh [DEST]
# Env:
#   LATIN_DOCUMENTS_ROOT — default destination if DEST omitted (else ~/src/latin_documents)

set -euo pipefail

default_dest="${LATIN_DOCUMENTS_ROOT:-$HOME/src/latin_documents}"
dest="${1:-$default_dest}"
url="https://github.com/ideasrule/latin_documents.git"

if [[ -d "${dest}/.git" ]]; then
  echo "Already a git repo: ${dest}"
  git -C "${dest}" remote -v | head -2 || true
else
  mkdir -p "$(dirname "${dest}")"
  git clone --depth 1 "${url}" "${dest}"
fi

echo ""
echo "Training page images + PageXML: ${dest}/data"
echo "Line OCR CSVs (upstream):       ${dest}/train_line_list.csv  ${dest}/val_line_list.csv"
echo "Docs: docs/latin-documents-training-data.md"
