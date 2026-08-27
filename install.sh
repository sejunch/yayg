#!/usr/bin/env bash
# yayg 를 사용자 홈에 설치한다 (root 불필요). 되돌리려면 ./install.sh --uninstall
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
LIB="$DATA/yayg"
BIN="$HOME/.local/bin"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor/scalable/apps"
DESKTOP_ID="io.github.yayg"

refresh_caches() {
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" || true
    command -v gtk-update-icon-cache >/dev/null &&
        gtk-update-icon-cache -qtf "$DATA/icons/hicolor" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" || "${1:-}" == "-u" ]]; then
    rm -rf "$LIB"
    rm -f "$BIN/yayg" "$APPS/$DESKTOP_ID.desktop" "$ICONS/$DESKTOP_ID.svg"
    refresh_caches
    echo "제거 완료"
    exit 0
fi

command -v python3 >/dev/null || { echo "python3 가 필요합니다" >&2; exit 1; }
python3 -c 'import gi; gi.require_version("Adw","1")' 2>/dev/null ||
    { echo "python-gobject 와 libadwaita 가 필요합니다" >&2; exit 1; }

mkdir -p "$LIB" "$BIN" "$APPS" "$ICONS"

# 앱 본체
rm -rf "$LIB/yayg"
cp -r "$SRC/yayg" "$LIB/"
cp "$SRC/run.py" "$LIB/"
find "$LIB" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# 실행 스크립트
cat > "$BIN/yayg" <<SH
#!/usr/bin/env bash
exec python3 "$LIB/run.py" "\$@"
SH
chmod +x "$BIN/yayg"

# 아이콘
install -Dm644 "$SRC/data/$DESKTOP_ID.svg" "$ICONS/$DESKTOP_ID.svg"

# 데스크톱 항목 — 런처는 로그인 셸의 PATH 를 물려받지 않을 수 있으므로
# Exec 을 절대 경로로 바꿔 넣는다.
sed "s|^Exec=yayg$|Exec=$BIN/yayg|" "$SRC/data/$DESKTOP_ID.desktop" \
    > "$APPS/$DESKTOP_ID.desktop"
chmod 644 "$APPS/$DESKTOP_ID.desktop"

if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate --no-hints "$APPS/$DESKTOP_ID.desktop" ||
        echo "경고: 데스크톱 항목 검증에서 문제가 보고되었습니다" >&2
fi

refresh_caches

echo "설치 완료"
echo "  실행 파일   $BIN/yayg"
echo "  런처 항목   $APPS/$DESKTOP_ID.desktop"
echo "  아이콘      $ICONS/$DESKTOP_ID.svg"
echo
echo "앱 런처에서 'yayg' 로 검색하세요. 목록에 바로 안 보이면 런처를 다시 열거나"
echo "데스크톱 세션을 다시 로그인하면 됩니다."
