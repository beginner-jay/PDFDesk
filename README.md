# PDF 정리 V1

Windows 10/11과 macOS에서 사용하는 오프라인 PDF 합치기·나누기 프로그램입니다. 원본 PDF는 수정하지 않으며 모든 결과를 새 파일로 저장합니다.

## 실행

Python 3.10 이상이 필요합니다.

```bash
python -m venv .venv

# macOS
.venv/bin/python -m pip install -e .
.venv/bin/python main.py

# Windows
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python main.py
```

## 테스트

```bash
# macOS
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest -v

# Windows PowerShell
$env:QT_QPA_PLATFORM="offscreen"
.venv\Scripts\python -m unittest -v
```

## V1 기능

- 여러 PDF 합치기
- 파일 드래그앤드롭과 마우스 순서 변경
- 위·아래 버튼을 이용한 순서 변경
- 일정한 페이지 수로 나누기
- 여러 페이지 범위를 지정하여 나누기
- 예상 결과와 제외 페이지 수 표시
- 백그라운드 처리, 진행 표시, 취소
- 임시 파일 검증과 기존 파일 덮어쓰기 방지

암호 PDF, 전자서명 보존, 압축, OCR과 페이지 미리보기는 V1에서 지원하지 않습니다. 자세한 설계는 [DESIGN.md](DESIGN.md)를 참고하세요.

## 배포 파일 만들기

PyInstaller는 현재 운영체제용 배포 파일을 만듭니다. macOS 앱은 macOS에서, Windows 실행 파일은 Windows에서 각각 빌드해야 합니다.

```bash
python -m pip install -e ".[build]"
pyinstaller --noconfirm --clean PDFDesk.spec
```

- macOS 결과: `dist/PDFDesk.app`
- Windows 결과: `dist/PDFDesk/PDFDesk.exe`

기관 외부에 배포하기 전에는 Windows 코드 서명과 macOS Developer ID 서명 및 공증이 필요합니다.
