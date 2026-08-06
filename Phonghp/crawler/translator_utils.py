import os
import re
import ahocorasick
import gc

class VietPhraseTranslator:
    def __init__(self):
        self.automaton = ahocorasick.Automaton()
        self.dict_path = os.path.join(os.path.dirname(__file__), "dicts")
        self.load_all_dicts()

    def load_all_dicts(self):
        """Nạp từ điển thông minh và giải phóng RAM"""
        if not os.path.exists(self.dict_path):
            print(f"❌ Không tìm thấy thư mục: {self.dict_path}")
            return

        all_files = [f for f in os.listdir(self.dict_path) if f.endswith(".txt")]
        priority_keywords = ["Name", "Names", "PhatAm", "NPC", "Place"]
        priority_files = [f for f in all_files if any(key in f for key in priority_keywords)]
        common_files = [f for f in all_files if f not in priority_files]
        
        ordered_files = common_files + priority_files
        print(f"--- Đang nạp {len(ordered_files)} file từ điển... ---")

        raw_dict = {}
        for filename in ordered_files:
            full_path = os.path.join(self.dict_path, filename)
            try:
                with open(full_path, "r", encoding="utf-8-sig", errors='ignore') as f:
                    for line in f:
                        if '=' in line:
                            parts = line.strip().split('=')
                            if len(parts) >= 2:
                                key = parts[0].strip()
                                val = parts[1].split('|')[0].split('/')[0].strip()
                                if key:
                                    raw_dict[key] = val
            except Exception as e:
                print(f"⚠️ Lỗi nạp file {filename}: {e}")

        for key, value in raw_dict.items():
            try:
                self.automaton.add_word(key, (len(key), value))
            except:
                continue
                
        self.automaton.make_automaton()
        del raw_dict
        gc.collect()
        print(f"✅ Đã nạp xong từ điển vào RAM.")

    def post_process(self, text):
        """Dọn dẹp văn bản: Fix lỗi maketrans lệch ký tự"""
        if not text: return ""

        # SỬA LỖI TẠI ĐÂY: 8 ký tự bên trái ứng với 8 ký tự bên phải
        # Vế trái: ， 。 ！ ？ ： ； （ ）
        # Vế phải: , . ! ? : ; ( )
        translation_table = str.maketrans('，。！？：；（）', ',.!?:;()')
        text = text.translate(translation_table)

        # Chuẩn hóa khoảng trắng
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([,.;:!?\)])', r'\1', text)
        text = re.sub(r'([,.;:!?])(?=[^\s\d])', r'\1 ', text)

        text = text.strip()
        if not text: return ""
        
        # Viết hoa chữ đầu
        text = text[0].upper() + text[1:]
        
        def uppercase_match(m):
            return m.group(1) + m.group(2).upper()
        
        # Viết hoa sau dấu chấm, hỏi, than
        text = re.sub(r'([.!?]\s+)([a-zà-ỹđ])', uppercase_match, text)

        return text

    def convert(self, text):
        """Dịch cụm từ dài nhất"""
        if not text: return ""
        
        matches = []
        for end_index, (length, value) in self.automaton.iter(text):
            start_index = end_index - length + 1
            matches.append((start_index, end_index, value))
        
        if not matches: return text
        
        matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        
        final_output = []
        last_idx = 0
        for start, end, value in matches:
            if start < last_idx: continue
            if start > last_idx:
                final_output.append(text[last_idx:start])
            
            final_output.append(value + " ")
            last_idx = end + 1
            
        final_output.append(text[last_idx:])
        return self.post_process("".join(final_output))

# Khởi tạo duy nhất một instance
translator = VietPhraseTranslator()

def translate_text(text, limit=None):
    """Giữ nguyên xuống dòng của chương truyện"""
    if not text: return ""
    if limit: text = text[:limit]

    # Xử lý theo từng dòng để bảo toàn cấu trúc văn bản
    lines = text.splitlines()
    translated_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            translated_lines.append(translator.convert(stripped))
        else:
            translated_lines.append("") 
            
    return "\n".join(translated_lines)
