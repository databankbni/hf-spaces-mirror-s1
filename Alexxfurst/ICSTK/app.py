import pandas as pd
import re
import math
from collections import Counter
from pathlib import Path
import gradio as gr

# ------------------- НАСТРОЙКА БАЗОВОГО ТК -------------------
BASE_TK_TYPE = 'ТК'
BASE_TK_NUMBER = '285'

# ------------------- СТОП-СЛОВА -------------------
STOP_WORDS = set('и в на с по для от из к ко не но или что как это его ее их все вся этот эта'.split())

# ------------------- СЛОВАРЬ СИНОНИМОВ -------------------
SYNONYM_GROUPS = [
    ['термопласт', 'полимер', 'полимерн', 'пластмасс', 'пластик', 'полиэтилен', 'пвх', 'пп', 'пвдф', 'полипропилен', 'полибутен', 'пб'],
    ['труб', 'трубопровод', 'трубопроводн'],
    ['листов', 'лист', 'пленк'],
    ['конструкц', 'конструкци'],
    ['сварк', 'сварн', 'спаива', 'пайк'],
    ['соединен', 'соедин', 'стык', 'шов'],
    ['экструз', 'экструдер'],
    ['детал', 'деталей', 'деталь', 'детали'],
    ['фитинг', 'фитинги'],
    ['материал', 'материалов'],
    ['процесс', 'процессы', 'процедур'],
]

# ------------------- ДОПОЛНИТЕЛЬНЫЕ ОГРАНИЧЕНИЯ -------------------
ADDITIONAL_RESTRICTIONS = {
    ('ТК', '364'): 'кроме соединений полимерных труб, листов и конструкций',
}

# ------------------- ЗАГРУЗКА ДАННЫХ -------------------
def load_data():
    file_path = Path('Справочник_ТК.xlsx')
    if not file_path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден в корне Space!")
    df = pd.read_excel(file_path)
    df.columns = [c.strip() for c in df.columns]
    return df

df = load_data()
print(f"✅ База данных загружена: {len(df)} записей")

# ------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -------------------
def normalize_word(word):
    word = word.lower()
    for group in SYNONYM_GROUPS:
        for syn in group:
            if word.startswith(syn) or syn.startswith(word):
                return group[0]
    return word

def get_normalized_words(text):
    if not isinstance(text, str):
        return set()
    words = re.findall(r'[а-яёa-z0-9]+', text.lower())
    return set(normalize_word(w) for w in words if len(w) > 2 and w not in STOP_WORDS)

def tokenize(text):
    if not isinstance(text, str):
        return []
    text = text.lower()
    words = re.findall(r'[а-яёa-z0-9]+', text)
    seen = set()
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS and not (w in seen or seen.add(w))]

def get_synonyms(word):
    word = word.lower()
    result = {word}
    for group in SYNONYM_GROUPS:
        if any(word.startswith(syn) or syn.startswith(word) for syn in group):
            result.update(group)
    return result

EXCLUSION_MARKERS = ['кроме', 'за исключением', 'исключая', 'не распространяется на']

def check_query_falls_under_exclusion(query, exclusion_text):
    if not exclusion_text or not isinstance(exclusion_text, str):
        return False
    query_norm = query.lower()
    exclusion_norm = exclusion_text.lower()
    has_exclusion = any(marker in exclusion_norm for marker in EXCLUSION_MARKERS)
    if not has_exclusion:
        return False
    excluded_phrase = ''
    for marker in EXCLUSION_MARKERS:
        if marker in exclusion_norm:
            idx = exclusion_norm.find(marker)
            excluded_phrase = exclusion_norm[idx + len(marker):].strip()
            break
    if not excluded_phrase:
        return False
    excluded_words = re.findall(r'[а-яёa-z0-9]+', excluded_phrase)
    excluded_words = [w for w in excluded_words if len(w) > 3]
    query_words = re.findall(r'[а-яёa-z0-9]+', query_norm)
    query_words = [w for w in query_words if len(w) > 3 and w not in STOP_WORDS]
    matched_terms = []
    for q_word in query_words:
        q_synonyms = get_synonyms(q_word)
        for e_word in excluded_words:
            e_synonyms = get_synonyms(e_word)
            if q_synonyms & e_synonyms:
                matched_terms.append((q_word, e_word))
                break
            if e_word in q_word or q_word in e_word:
                matched_terms.append((q_word, e_word))
                break
    if len(matched_terms) >= 1:
        return True, matched_terms, excluded_phrase
    return False

# ------------------- ОСНОВНАЯ ЛОГИКА АНАЛИЗА -------------------
def analyze_code_for_base_tk(code, classifier_type, dataframe, query, standard_type):
    mask = (dataframe['Код'] == code) & (dataframe['Тип классификатора (унифицированный)'] == classifier_type)
    all_occurrences = dataframe[mask].copy()
    if all_occurrences.empty:
        return False, [], None, [], 0
    base_mask = (all_occurrences['Тип ТК'] == BASE_TK_TYPE) & (all_occurrences['Номер ТК'].astype(str) == BASE_TK_NUMBER)
    base_rows = all_occurrences[base_mask]
    other_rows = all_occurrences[~base_mask]
    if base_rows.empty:
        return False, [], None, [], 0
    base_info = {
        'name': base_rows.iloc[0]['Наименование'],
        'restriction': str(base_rows.iloc[0].get('Ограничение / Область применения', '')).strip(),
        'notes': str(base_rows.iloc[0].get('Доп. примечания', '')).strip()
    }
    if standard_type == 'ГОСТ Р':
        other_rows = other_rows[other_rows['Тип ТК'] != 'МТК']
    total_other_tks = len(other_rows)
    if other_rows.empty:
        return True, [], base_info, [], 0
    other_tks = []
    excluded_tks = []
    for _, row in other_rows.iterrows():
        tk_key = (row['Тип ТК'], str(row['Номер ТК']))
        restriction = str(row.get('Ограничение / Область применения', '')).strip()
        notes = str(row.get('Доп. примечания', '')).strip()
        additional = ADDITIONAL_RESTRICTIONS.get(tk_key, '')
        combined_restriction = restriction
        if additional and additional not in ['полный охват', 'nan', '']:
            combined_restriction = f"{restriction} | {additional}" if restriction not in ['полный охват', 'nan', ''] else additional
        exclusion_result = check_query_falls_under_exclusion(query, combined_restriction)
        tk_data = {
            'tk_type': row['Тип ТК'],
            'tk_number': str(row['Номер ТК']),
            'tk_name': row['Наименование ТК'],
            'restriction': restriction,
            'notes': notes,
            'additional_restriction': additional,
            'combined_restriction': combined_restriction
        }
        if exclusion_result and exclusion_result[0]:
            _, matched_terms, excluded_phrase = exclusion_result
            tk_data['exclusion_reason'] = {
                'matched_terms': matched_terms,
                'excluded_phrase': excluded_phrase
            }
            excluded_tks.append(tk_data)
        else:
            other_tks.append(tk_data)
    is_unique = len(other_tks) == 0
    return is_unique, other_tks, base_info, excluded_tks, total_other_tks

def search_codes_for_base_tk(query, standard_type):
    if not query or not query.strip():
        return None, None, "Введите наименование стандарта"
    query_words = tokenize(query)
    if not query_words:
        return None, None, "В запросе нет значимых слов"
    query_words_normalized_all = [normalize_word(w) for w in query_words]
    query_word_counts = Counter(query_words_normalized_all)
    query_words_normalized = list(set(query_words_normalized_all))
    first_word = normalize_word(query_words[0]) if query_words else ''
    theme_keywords = set()
    for _, row in df.iterrows():
        if row['Тип ТК'] == BASE_TK_TYPE and str(row['Номер ТК']) == BASE_TK_NUMBER:
            name_code_words = get_normalized_words(str(row.get('Наименование', '')))
            for word in query_words_normalized:
                if word in name_code_words:
                    theme_keywords.add(word)
    base_df = df[(df['Тип ТК'] == BASE_TK_TYPE) & (df['Номер ТК'].astype(str) == BASE_TK_NUMBER)]
    total_docs = len(base_df)
    word_doc_freq = {}
    for _, row in base_df.iterrows():
        name_code_words = get_normalized_words(str(row.get('Наименование', '')))
        for word in name_code_words:
            if word not in word_doc_freq:
                word_doc_freq[word] = 0
            word_doc_freq[word] += 1
    word_idf = {}
    for word, freq in word_doc_freq.items():
        word_idf[word] = math.log((total_docs + 1) / (freq + 1)) + 1
    scores = []
    theme_scores = []
    for idx, row in df.iterrows():
        name_code_words = get_normalized_words(str(row.get('Наименование', '')))
        name_tk_words = get_normalized_words(str(row.get('Наименование ТК', '')))
        restriction_words = get_normalized_words(str(row.get('Ограничение / Область применения', '')))
        notes_words = get_normalized_words(str(row.get('Доп. примечания', '')))
        score = 0
        theme_score = 0
        matched_in_name = set()
        for word in query_words_normalized:
            if word in name_code_words and word not in matched_in_name:
                score += 5
                matched_in_name.add(word)
                if word in theme_keywords:
                    idf_weight = word_idf.get(word, 1.0)
                    freq_weight = query_word_counts[word]
                    if word == first_word:
                        theme_score += 10
                    theme_score += freq_weight * 100 * idf_weight * 3
                    score += 10
            if word in name_tk_words:
                score += 3
                if word in theme_keywords:
                    idf_weight = word_idf.get(word, 1.0)
                    theme_score += query_word_counts[word] * 50 * idf_weight * 3
            if word in restriction_words:
                score += 2
                if word in theme_keywords:
                    idf_weight = word_idf.get(word, 1.0)
                    theme_score += query_word_counts[word] * 30 * idf_weight * 3
            if word in notes_words:
                score += 1
        restriction = str(row.get('Ограничение / Область применения', '')).strip()
        if restriction and restriction not in ['полный охват', 'nan', '']:
            restriction_normalized = get_normalized_words(restriction)
            overlap = restriction_normalized & set(query_words_normalized)
            if overlap:
                theme_score += len(overlap) * 500
        scores.append(score)
        theme_scores.append(theme_score)
    df_res = df.copy()
    df_res['score'] = scores
    df_res['theme_score'] = theme_scores
    base_mask = (df_res['Тип ТК'] == BASE_TK_TYPE) & (df_res['Номер ТК'].astype(str) == BASE_TK_NUMBER)
    base_records = df_res[base_mask & (df_res['score'] > 0)].copy()
    if base_records.empty:
        return None, None, f"По запросу «{query}» не найдено кодов ТК {BASE_TK_NUMBER}"
    unique_codes = base_records.drop_duplicates(subset=['Код', 'Тип классификатора (унифицированный)'])
    all_codes = []
    for _, row in unique_codes.iterrows():
        code = row['Код']
        classifier = row['Тип классификатора (унифицированный)']
        is_unique, other_tks, base_info, excluded_tks, total_other_tks = analyze_code_for_base_tk(
            code, classifier, df, query, standard_type
        )
        ideal_bonus = 0
        if is_unique and total_other_tks > 0:
            ideal_bonus = 2000
        final_score = int(row['score']) + int(row['theme_score']) + ideal_bonus
        code_data = {
            'code': code,
            'classifier': classifier,
            'name': base_info['name'] if base_info else row['Наименование'],
            'base_restriction': base_info['restriction'] if base_info else '',
            'base_notes': base_info['notes'] if base_info else '',
            'score': int(row['score']),
            'theme_score': int(row['theme_score']),
            'ideal_bonus': ideal_bonus,
            'final_score': final_score,
            'is_unique': is_unique,
            'other_tks': other_tks,
            'excluded_tks': excluded_tks,
            'total_other_tks': total_other_tks
        }
        all_codes.append(code_data)
    all_codes.sort(key=lambda x: x['final_score'], reverse=True)
    return all_codes, query_words, None

# ------------------- ФУНКЦИЯ ДЛЯ GRADIO -------------------
def analyze_and_display(query, standard_type):
    if not query or not query.strip():
        return "⚠️ Пожалуйста, введите запрос.", None, None
    result, keywords, error = search_codes_for_base_tk(query, standard_type)
    if error:
        return f"❌ {error}", None, None
    oks_codes = [c for c in result if c['classifier'] == 'ОКС']
    okpd2_codes = [c for c in result if c['classifier'] == 'ОКПД2']
    report_lines = []
    report_lines.append(f"## 📊 Результаты анализа по запросу: «{query}»")
    report_lines.append(f"**Тип стандарта:** {standard_type}")
    report_lines.append(f"**Ключевые слова:** `{', '.join(keywords)}`")
    report_lines.append("")
    unique_count = sum(1 for c in result if c['is_unique'])
    total = len(result)
    report_lines.append(f"**Всего кодов:** {total}, из них уникальных для ТК 285: {unique_count}")
    report_lines.append("")
    if oks_codes:
        report_lines.append("### 📘 Наиболее подходящие коды ОКС")
        for i, c in enumerate(oks_codes[:10], 1):
            status = "✅ уникальный" if c['total_other_tks'] == 0 else ("🟡 другие ТК исключены" if c['is_unique'] else "🔴 риск пересечения")
            report_lines.append(f"{i}. `{c['code']}` — {c['name']} (релевантность: {c['final_score']}) — {status}")
        if len(oks_codes) > 10:
            report_lines.append(f"*... и ещё {len(oks_codes)-10} кодов*")
    else:
        report_lines.append("### 📘 Коды ОКС не найдены")
    report_lines.append("")
    if okpd2_codes:
        report_lines.append("### 📗 Наиболее подходящие коды ОКПД2")
        for i, c in enumerate(okpd2_codes[:10], 1):
            status = "✅ уникальный" if c['total_other_tks'] == 0 else ("🟡 другие ТК исключены" if c['is_unique'] else "🔴 риск пересечения")
            report_lines.append(f"{i}. `{c['code']}` — {c['name']} (релевантность: {c['final_score']}) — {status}")
        if len(okpd2_codes) > 10:
            report_lines.append(f"*... и ещё {len(okpd2_codes)-10} кодов*")
    else:
        report_lines.append("### 📗 Коды ОКПД2 не найдены")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("ℹ️ **Детальная информация** представлена в таблице ниже.")
    text_report = "\n".join(report_lines)
    # Создаём таблицу для топ-кодов
    top_codes = result[:20]
    df_display = pd.DataFrame([{
        'Код': c['code'],
        'Тип': c['classifier'],
        'Наименование': c['name'],
        'Релевантность': c['final_score'],
        'Уникальность': '✅' if c['total_other_tks'] == 0 else ('🟡 исключены' if c['is_unique'] else '❌ пересечение'),
        'Другие ТК': len(c['other_tks']),
        'Исключенные ТК': len(c['excluded_tks'])
    } for c in top_codes])
    # Детали в JSON
    details_json = result
    return text_report, df_display, details_json

# ------------------- ИНТЕРФЕЙС GRADIO -------------------
with gr.Blocks(title="Подбор ТК 285") as demo:
    gr.Markdown("## 🔍 Интеллектуальный подбор уникальных кодов ОКС/ОКПД2 для ТК 285")
    gr.Markdown("Система анализирует запрос и показывает подходящие коды с учётом пересечений с другими техническими комитетами.")
    
    with gr.Row():
        with gr.Column(scale=2):
            query_input = gr.Textbox(
                label="📝 Введите наименование проекта стандарта",
                lines=3,
                placeholder="Например: Трубы и фитинги пластмассовые. Процедуры сварки нагретым инструментом встык...",
                value=""
            )
        with gr.Column(scale=1):
            standard_type = gr.Radio(
                choices=["ГОСТ Р", "ГОСТ"],
                label="📌 Тип стандарта",
                value="ГОСТ Р",
                info="ГОСТ Р — национальный, ГОСТ — межгосударственный"
            )
    
    with gr.Row():
        analyze_btn = gr.Button("🔍 Анализировать", variant="primary")
    
    with gr.Row():
        with gr.Column():
            output_text = gr.Markdown("### 📊 Результаты анализа")
        with gr.Column():
            output_table = gr.Dataframe(
                label="Топ-20 кодов (сводка)",
                interactive=False,
                wrap=True
            )
    
    with gr.Row():
        output_json = gr.JSON(label="📄 Детальная информация по всем кодам (JSON)")
    
    analyze_btn.click(
        fn=analyze_and_display,
        inputs=[query_input, standard_type],
        outputs=[output_text, output_table, output_json]
    )
    
    gr.Markdown("### 📌 Примеры запросов")
    examples = [
        "Трубы и фитинги пластмассовые. Процедуры сварки нагретым инструментом встык",
        "Методы испытаний сварных соединений полимерных труб",
        "Соединения полимерных листов и конструкций"
    ]
    for ex in examples:
        btn = gr.Button(ex, size="sm")
        btn.click(lambda q=ex: q, None, query_input)

# ------------------- ЗАПУСК ДЛЯ HF SPACE (без условий) -------------------
demo.launch(ssr_mode=False)