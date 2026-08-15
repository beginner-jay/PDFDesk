# PDFDesk V1

[![Build Windows](https://github.com/beginner-jay/PDFDesk/actions/workflows/build-windows.yml/badge.svg)](https://github.com/beginner-jay/PDFDesk/actions/workflows/build-windows.yml)

Windows 10/11과 macOS에서 사용하는 오프라인 PDF 합치기·나누기 프로그램입니다. 일반 사무직, 공무원, PC 사용이 익숙하지 않은 사용자를 기준으로 설계했으며 원본 PDF는 변경하지 않고 모든 결과를 새 파일로 저장합니다.

## 주요 기능

### PDF 합치기

- 여러 PDF를 파일 선택 또는 드래그앤드롭으로 추가
- 파일 행을 마우스로 끌거나 `위`·`아래` 버튼으로 순서 변경
- 파일별 페이지 수와 전체 파일·페이지 수 표시
- 개별 파일 삭제, 저장 위치와 결과 파일명 지정

### PDF 나누기

- 합치기 화면과 동일한 파일 선택·드래그앤드롭 영역
- 숫자만 입력 가능한 `[50]쪽씩 나누기` 방식
- 페이지 범위를 직접 지정하여 범위별 PDF 생성
- 기본 범위 한 개에서 시작하여 필요한 만큼 범위 추가
- 예상 파일명, 결과 파일 수, 저장되지 않는 페이지 수 표시

### 안전한 처리

- 대용량 작업 중 화면이 멈추지 않는 백그라운드 처리
- 진행률 표시와 작업 취소
- 임시 파일을 검증한 후 결과 저장
- 기존 파일을 덮어쓰지 않고 새 이름으로 저장

## 실행 방법

Python 3.10 이상이 필요합니다.

### macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python main.py
```

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python main.py
```

`ModuleNotFoundError: No module named 'PySide6'`가 표시되면 가상환경을 활성화하지 않았거나 의존성을 설치하지 않은 상태입니다. 위 설치 명령을 먼저 실행하세요.

## 테스트

```bash
# macOS
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest -v
```

```powershell
# Windows PowerShell
$env:QT_QPA_PLATFORM="offscreen"
.venv\Scripts\python -m unittest -v
```

현재 PDF 병합·분할, 범위 검증, 파일명 충돌 방지 등을 검사하는 자동 테스트 12개가 있습니다.

## 배포 파일

### Windows

`main` 브랜치에 변경 사항을 올리면 GitHub Actions가 다음 과정을 자동으로 실행합니다.

1. 의존성 설치와 자동 테스트
2. PyInstaller Windows 앱 빌드
3. 패키징된 `PDFDesk.exe` 실행 확인
4. `PDFDesk-Windows-x64` ZIP 아티팩트 업로드

완료된 파일은 [Build Windows Actions](https://github.com/beginner-jay/PDFDesk/actions/workflows/build-windows.yml)에서 해당 실행을 선택한 뒤 `Artifacts` 영역에서 받을 수 있습니다. 첫 Windows 빌드와 실행 확인은 성공했으며 아티팩트 크기는 약 37.8MB입니다.

### macOS

PySide6 전체 패키지 대신 `PySide6-Essentials`를 사용하고 불필요한 Qt 모듈·플러그인·번역을 제외했습니다. Apple Silicon용 배포 ZIP은 로컬 빌드 기준 약 24MB입니다.

### 직접 빌드

PyInstaller는 실행 중인 운영체제용 파일만 만듭니다. Windows용 앱은 Windows에서, macOS용 앱은 macOS에서 각각 빌드해야 합니다.

```bash
python -m pip install -e ".[build]"
pyinstaller --noconfirm --clean PDFDesk.spec
```

- macOS: `dist/PDFDesk.app`
- Windows: `dist/PDFDesk/PDFDesk.exe`

기관 외부에 배포할 때는 Windows 코드 서명과 macOS Developer ID 서명·공증을 별도로 적용해야 합니다.

## 기술 구성

| 구분 | 사용 기술 |
|---|---|
| 언어 | Python 3.10+ |
| 화면 | PySide6-Essentials / Qt Widgets |
| PDF 처리 | pypdf |
| 패키징 | PyInstaller |
| 테스트 | unittest |
| Windows CI | GitHub Actions |

## 프로젝트 구성

| 파일 | 역할 |
|---|---|
| `main.py` | 화면, 드래그앤드롭, 작업 진행과 사용자 안내 |
| `pdf_ops.py` | PDF 정보 읽기, 합치기, 페이지 수·범위 나누기 |
| `test_pdf_ops.py` | PDF 처리 자동 테스트 |
| `PDFDesk.spec` | Windows/macOS PyInstaller 설정 |
| `DESIGN.md` | V1 사용자 경험과 기능 설계 |
| `FUTURE_UPDATE_PLAN.md` | 미리보기와 용량 최적화 등 추후 업데이트 검토 |

## V1 제한 사항

- 암호가 설정된 PDF
- 전자서명 보존
- OCR, PDF 압축과 편집
- 페이지 미리보기와 썸네일

미리보기와 30MB 이하 설치 앱을 함께 목표로 하는 차기 버전 검토 내용은 [FUTURE_UPDATE_PLAN.md](FUTURE_UPDATE_PLAN.md)를 참고하세요.
