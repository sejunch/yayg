# yayg

`yay` 위에 얹은 GTK4 / libadwaita 패키지 관리자.

검색·설치·삭제·업그레이드를 **전부 yay가 그대로 수행**한다. yayg는 목록을 보여주고
yay를 pty 위에서 실행해 그 출력을 창 안에 그려줄 뿐이라, 터미널에서 직접
`yay -S ...` 를 친 것과 결과가 같다.

## 기능

- **검색** — 저장소와 AUR을 한 번에 (`yay -Ss`). 정확히 일치 → 접두사 일치 → 부분 일치
  순으로 정렬하고, 같은 순위에서는 공식 저장소를 AUR보다 먼저, AUR끼리는 인기도순으로 놓는다.
- **설치됨** — `pacman -Qi` 전체 파싱. 전체 / 명시적 설치 / AUR·외부 / 고아 패키지로
  거르고 이름순·크기순 정렬. 상단에 개수와 용량 합계가 나온다.
- **업데이트** — `checkupdates` + `yay -Qua`. 개별 업그레이드와 전체 업그레이드 모두 지원.
- **상세 정보** — 버전·라이선스·용량·의존성·관리자·인기도 등. 웹사이트와 AUR 페이지 링크.
- **고아 패키지 정리** — 메뉴에서 `-Rns` 로 한 번에.
- **PKGBUILD 미리보기** — AUR 패키지를 설치·업그레이드하기 전에 PKGBUILD와 딸린
  `.install` 스크립트를 보여준다. 문법 강조, 관리자·투표수·최종 수정일, 그리고
  흔히 눈여겨볼 표현(`sudo`, `curl | sh`, `systemctl enable`, `http://` 소스 등)에
  줄 표시. **보안 검사가 아니라 시선을 먼저 가게 하는 표시일 뿐이다** — 정상적인
  쓰임도 많다. 설정에서 끌 수 있다.
- **패키지 아이콘** — 목록과 상세 패널에 실제 앱 아이콘을 보여준다. 아이콘이 없는
  패키지(대부분의 라이브러리)는 저장소 이름 배지로 대체된다. 설정에서 끌 수 있다.
- **다중 선택** — 헤더의 선택 버튼(Ctrl+S)으로 여러 패키지를 골라 한 트랜잭션으로
  설치·삭제·업그레이드. sudo 도 한 번, 의존성 해석도 한 번이면 된다.
- **삭제 영향 미리보기** — `-Rns` 는 의존성을 타고 예상보다 많이 지운다. 실제로
  무엇이 지워지고 얼마가 회수되는지 먼저 보여준다.
- **업그레이드 전 Arch 뉴스** — 마지막 전체 업그레이드 이후 올라온 공지를 확인하고,
  수동 개입이 필요한 글을 표시한다. 공지를 놓치고 `-Syu` 하는 것이 Arch 에서 가장
  흔한 사고다.
- **버전 변경(다운그레이드)** — 로컬 캐시와 Arch Linux Archive 에서 예전(또는 다른)
  버전을 골라 `-U` 로 설치.
- **디스크 정리** — pacman 캐시·yay 빌드 캐시·고아 패키지가 각각 얼마를 쓰고 있고
  얼마나 회수되는지 보고 그 자리에서 정리.
- **변경 이력** — `pacman.log` 로 보는 최근 설치·업그레이드·삭제 기록. 항목을 누르면
  그 패키지 상세로 이동한다.
- **의존성 탐색** — 상세 패널의 의존성 이름을 누르면 그 패키지로 이동.
- **설치 이유 변경** — 명시적 설치 ↔ 의존성 설치를 상세 패널에서 바로 전환.
- **스크린샷** — AppStream 에 있는 경우 상세 패널에 표시 (기본 꺼짐, 아래 참조).
- **설정 창** — 아래 참조.

## 요구 사항

Arch Linux(또는 파생) + 아래 패키지. **모두 기본 Arch 데스크톱에 이미 있는 것들이고,
추가 파이썬 의존성은 없다.**

```
yay  python  python-gobject  gtk4  libadwaita  pacman-contrib  archlinux-appstream-data
```

- `pacman-contrib`(= `checkupdates`) 가 없으면 저장소 업데이트 확인이
  `yay -Qu --repo` 로 대체된다.
- `archlinux-appstream-data` 가 없으면 설치되지 않은 패키지의 아이콘만 안 나온다.
  설치된 패키지 아이콘과 나머지 기능은 그대로 동작한다.

## 실행

```bash
python3 run.py
```

앱 런처에 등록하려면 (root 불필요):

```bash
./install.sh                # 설치
./install.sh --uninstall    # 제거
```

들어가는 곳:

| 경로 | 내용 |
|---|---|
| `~/.local/share/yayg/` | 앱 본체 |
| `~/.local/bin/yayg` | 실행 스크립트 |
| `~/.local/share/applications/io.github.yayg.desktop` | 런처 항목 |
| `~/.local/share/icons/hicolor/scalable/apps/io.github.yayg.svg` | 아이콘 |

설치 후 런처에서 `yayg` · `패키지` · `aur` · `pacman` · `yay` · `arch` 중
아무거나로 검색하면 나온다.

데스크톱 항목의 `Exec` 은 설치 시점에 절대 경로로 기록된다. 앱 런처는 로그인 셸의
`PATH` 를 물려받지 않는 경우가 있어서 `Exec=yayg` 로는 안 뜰 수 있기 때문이다.

## 단축키

| 키 | 동작 |
|---|---|
| `Ctrl+F` | 검색창으로 이동 |
| `Ctrl+R` | 현재 페이지 새로고침 |
| `Ctrl+U` | 시스템 전체 업그레이드 |
| `Ctrl+S` | 다중 선택 모드 |
| `Ctrl+,` | 설정 |

## 설정

`~/.config/yayg/settings.json` 에 저장된다. 창에서 바꾸면 바로 반영된다.

| 페이지 | 항목 |
|---|---|
| 일반 | 색 구성, 패키지 아이콘, 스크린샷, 시작 페이지, 업데이트 자동 확인 |
| 설치 | **PKGBUILD 미리보기**, **Arch 뉴스 확인**, `--removemake`, `--cleanafter`, `--devel`, **삭제 전 미리보기**, 삭제 방식 (`-Rns`/`-Rs`/`-R`) |
| 검색·업데이트 | AUR 결과 포함 여부, 결과 개수 제한, 저장소 확인 방법, AUR 업데이트 포함 여부 |
| 고급 | yay 추가 인자, 실제 실행될 명령 미리보기, 기본값 되돌리기 |

고급 페이지의 명령 미리보기는 지금 설정으로 실제 어떤 `yay` 명령이 나가는지
실시간으로 보여준다. 무엇이 바뀌는지 추측하지 않아도 된다.

## 설계 메모

**왜 pty인가.** GUI에서 `sudo`를 다루는 흔한 방법은 `pkexec`지만 yay는 root로 실행되기를
거부한다. 그래서 yayg는 파이썬 내장 `pty`로 yay를 띄운다. yay 입장에서는 진짜 터미널이라
평소처럼 동작하고, sudo 비밀번호·`[Y/n]` 확인·`Packages to exclude:` 같은 프롬프트가
그대로 다이얼로그 하단 입력줄로 전달된다. 비밀번호 프롬프트가 감지되면 입력이 자동으로
가려진다. VTE4를 설치할 필요가 없다는 것도 이유다.

`SUDO_PROMPT`를 고정해 로케일과 무관하게 프롬프트를 인식하고, `PAGER=cat` 등을 걸어
대화형 페이저가 떠서 UI가 멎는 일을 막는다. 캐리지 리턴은 줄 덮어쓰기로 해석해
pacman 진행률 표시줄이 한 줄에서 갱신되게 한다.

**스크린샷이 기본 꺼짐인 이유.** AppStream 은 아이콘은 로컬에 캐시해 두지만
스크린샷은 원본 주소만 담고 있다. 즉 켜면 패키지 상세를 열 때마다 각 프로젝트
웹사이트(gimp.org, blender.org …)에 직접 접속하게 된다. 그 판단은 사용자 몫이라
기본값을 꺼짐으로 두었다. 받은 이미지는 `~/.cache/yayg/screenshots` 에 보관한다.

**PKGBUILD diff.** 이미 설치한 AUR 패키지를 업데이트할 때는 전문 대신 "지난번에
빌드한 것에서 뭐가 바뀌었나" 를 먼저 보여준다. `~/.cache/yay/<pkgbase>/PKGBUILD`
(마지막으로 빌드한 시점의 파일)와 지금 AUR 에 있는 파일을 비교한다. 관리자 계정이
털렸을 때 드러나는 지점이 정확히 거기다.

**다운그레이드는 어디서 받는가.** 로컬 pacman 캐시를 먼저 보고, 없으면 Arch Linux
Archive(`archive.archlinux.org`)에서 찾는다. 캐시를 주기적으로 비우는 시스템에서는
캐시에 현재 버전밖에 없는 경우가 많아서, 아카이브가 사실상 유일한 경로다.

**아이콘을 어디서 가져오는가.** 두 갈래다. 설치된 패키지는 `pacman -Ql` 로 그
패키지가 소유한 `/usr/share/applications/*.desktop` 을 찾아 `Icon=` 을 읽는다
(AUR 패키지도 그대로 걸린다). 설치되지 않은 저장소 패키지는
`archlinux-appstream-data` 가 깔아 두는
`/usr/share/swcatalog/icons/<repo>/<크기>/<패키지>_<아이콘>.png` 를 쓴다 — 파일
이름에 패키지명이 들어 있어서 AppStream XML 을 파싱할 필요가 없다. 인덱스 구축은
전부 합쳐 0.3초쯤 걸리고, 목록을 읽는 같은 워커 스레드에서 미리 만들어 둔다.
설치·삭제 뒤에는 인덱스를 버리고 다시 만든다.

**왜 `yay -Sy`를 쓰지 않는가.** 업데이트 확인에 `-Sy`를 쓰면 동기화 DB만 앞서 나가
부분 업그레이드 위험이 생긴다. `checkupdates`는 임시 DB 복사본을 써서 그 위험이 없다.

**yay에 넘기는 플래그.** 설치·업그레이드에는 diff/편집 메뉴를 끄는 플래그가 항상
붙는다. 그 메뉴들은 대화형 페이저나 편집기를 띄워 창을 멈추게 하기 때문이다.
그래서 PKGBUILD 검토는 yay에 맡기지 않고 yayg가 직접 창으로 보여준다. 설치
확인(`[Y/n]`)은 일부러 남겨두어 사용자가 트랜잭션 창에서 직접 승인하게 한다.
`--noconfirm` 은 쓰지 않는다.

플래그 이름은 **버전마다 다르다**. yay v12 는 `--diffmenu=false --editmenu=false`,
예전 버전은 `--nodiffmenu --noeditmenu` 다. 틀린 이름을 넘기면 yay 가 아무것도 하지
않고 "잘못된 옵션" 으로 죽는다. 그래서 추측하지 않고 실행 시점에 물어본다 —
`yay <플래그> --version` 은 부작용이 없고 플래그가 유효할 때만 버전을 출력하므로,
이걸로 후보를 하나씩 확인해 통하는 쪽을 캐시한다. 어느 쪽도 안 되면 붙이지 않는다
(메뉴가 떠도 트랜잭션 창의 입력줄로 답할 수 있다). 지금 어떤 명령이 나가는지는
설정 > 고급에서 그대로 볼 수 있다.

**PKGBUILD를 어떻게 가져오는가.** `yay -G` 는 git clone 을 하므로 "설치 전에 잠깐
훑어본다"에는 무겁다. 대신 AUR RPC 로 `pkgbase` 를 알아낸 뒤 cgit 의 plain 뷰에서
`PKGBUILD` 를 받고, 그 안의 `install=` / `source=` 항목 중 원격 URL이 아닌 것들
(`.install`, 패치, `.desktop` 등)을 같이 받는다. 표준 라이브러리만 쓴다.

## 구조

```
run.py              진입점
install.sh          홈 디렉터리 설치/제거
data/               아이콘(SVG)과 데스크톱 항목
yayg/backend.py     yay/pacman 호출과 출력 파싱 (GTK 의존성 없음)
yayg/aur.py         AUR RPC/cgit 에서 PKGBUILD 받기 (GTK 의존성 없음)
yayg/icons.py       패키지 아이콘 인덱스 (GTK 의존성 없음)
yayg/appstream.py   AppStream 스크린샷 (GTK 의존성 없음)
yayg/news.py        Arch 뉴스 + 마지막 업그레이드 시각 (GTK 의존성 없음)
yayg/maintenance.py 디스크 사용량·다운그레이드 후보·pacman 로그 (GTK 의존성 없음)
yayg/settings.py    JSON 설정 저장 (GTK 의존성 없음)
yayg/runner.py      pty 트랜잭션 실행 — ANSI/CR 처리, 프롬프트 감지
yayg/transaction.py 진행 상황 다이얼로그
yayg/pkgbuild.py    PKGBUILD 검토 창 (전문 / 업데이트 diff)
yayg/dialogs.py     삭제 확인·뉴스·디스크 정리·버전 변경·변경 이력 창
yayg/preferences.py 설정 창
yayg/widgets.py     목록 행, 상세 정보 패널
yayg/window.py      메인 창과 세 페이지
yayg/util.py        스레드 헬퍼, 아이콘 테마 폴백
```

백엔드 호출은 전부 워커 스레드에서 돌고 `GLib.idle_add` 로 UI에 돌아온다. 검색·상세
조회는 세대 번호로 오래된 응답을 버린다. 목록은 40행씩 나눠 붙여서 1,400개짜리 설치
목록에서도 창이 멎지 않는다.

## 라이선스

MIT — [LICENSE](LICENSE) 참조.
