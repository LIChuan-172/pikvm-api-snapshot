import pytesseract
from pprint import pprint

def test_tesseract_languages():
    try:
        # 获取所有已安装的语言包
        print("\n=== Tesseract 信息 ===")
        print("Tesseract 路径:", pytesseract.pytesseract.tesseract_cmd)
        
        print("\n已安装的语言包:")
        languages = pytesseract.get_languages()
        pprint(languages)
        
    except Exception as e:
        print(f"错误: {e}")
        print("\n提示: 请确保已安装 Tesseract 和语言包")

if __name__ == "__main__":
    test_tesseract_languages()