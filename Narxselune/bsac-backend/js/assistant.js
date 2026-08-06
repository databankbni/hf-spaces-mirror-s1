// js/assistant.js

/* ==========================================================================
   БЛОК 1: ХРАНИЛИЩЕ ЗНАНИЙ И КОНФИГУРАЦИОННЫЕ ДАННЫЕ АССИСТЕНТА
   ========================================================================== */

/* БАЗОВАЯ ОПТИМИЗАЦИЯ ВЕБ-СТРАНИЦ (PERFORMANCE, SEO): Оптимизация производительности за счет структурирования текстовых баз в легковесные JS-объекты */
const assistantDatabase = [
    {
        keywords: ['документ', 'доки', 'паспорт', 'справка', 'аттестат', 'фото', 'что нести'],
        answer: 'Для подачи заявления в приемную комиссию Вам понадобятся следующие документы:<br>' +
            '1. 6 фотографий размером 3х4 см.<br>' +
            '2. ОРИГИНАЛЫ и копии всех документов об образовании и приложения к ним (свидетельство о базовом образовании, аттестат, диплом с приложением). Дополнительно делаем копии для себя.<br>' +
            '3. Медицинская справка о состоянии здоровья по форме, установленной Министерством здравоохранения, с указанием годности к выбранным специальностям, <b>(указывается полное наименование специальностей)</b> <br>' +
            '4. Документы, подтверждающие право абитуриента на льготы (при их наличии) (оригинал и копия).<br>' +
            '5. Заключение ВКК или МРЭК об отсутствии противопоказаний для обучения по выбранной специальности (для детей-инвалидов до 18 лет, инвалидов I, II и III группы).<br>' +
            '6. Копию свидетельства о браке (если документ об образовании и паспорт на разные фамилии). <br>' +
            '7. Паспорт или заменяющий его документ предъявляется абитуриентом лично приемной комиссии. <br>' +
            '<br>' +
            'ДОПОЛНИТЕЛЬНЫЕ ДОКУМЕНТЫ: <br>' +
            '<br>' +
            '<b>На уровень ССО:</b> <br>' +
            '1. Выписка (копия) из трудовой книжки, заверенная администрацией (для поступающих на заочную форму обучения).<br>' +
            '<br>' +
            '<b>На уровень ВО (полный срок): </b><br>' +
            '1. Оригиналы и копии сертификатов централизованного экзамена (централизованного тестирования)<br>' +
            '2. В медицинской справке при поступлении на группу специальностей указываются все специальности группы<br>' +
            '3. Характеристика (необходима тем, кто окончил учреждение образования в год поступления)<br>' +
            '<br>' +
            '<b>На уровень ВО (сокращенный срок): </b><br>' +
            '1. Характеристика (необходима тем, кто окончил учреждение образования в год поступления)<br>' +
            '2. Выписка (копия) из трудовой книжки, заверенная администрацией (для поступающих на заочную форму обучения).<br>' +
            '<br>' +
            '<b>Абитуриенты, не достигшие возраста 18 лет, подают документы в приемную комиссию в присутствии законного представителя (родителя, усыновителя, опекуна, попечителя)</b>'
    },
    {
        keywords: ['срок приема', 'сроки', 'когда подавать', 'календарь', 'до какого числа', 'период приема', 'прием документов', 'когда заканчивается', 'даты подачи'],
        answer: 'Прием документов в 2025 году осуществляется в следующие сроки:<br>' +
            '<br>' +
            '• <strong>На бюджет (ССО):</strong> (9 кл.) с 18 июля по 3 августа, (11 кл., ПТО) с 18 июля по 11 августа.<br>' +
            '• <strong>На платное (ССО):</strong> (9 кл.) с 18 июля по 10 августа, (11 кл., ПТО) с 18 июля по 15 августа.<br>' +
            'Зачисление на уровень ССО:<br>' +
            '• <strong>На бюджет (ССО):</strong> (9 кл.) по 6 августа, (11 кл., ПТО) по 13 августа.<br>' +
            '• <strong>На платное (SСО):</strong> (9 кл.) по 12 августа, (11 кл., ПТО) по 17 августа.<br>' +
            '<br>' +
            '• <strong>На бюджет (ВО):</strong> (11 кл.) с 12 июля по 17 июля, (ССО) с 12 июля по 17 июля.<br>' +
            '• <strong>На платное (ВО):</strong> (11 кл.) с 12 июля по 1 августа, (ССО) с 12 июля по 17 июля.<br>' +
            'Зачисление на уровень ВО:<br>' +
            '• <strong>На бюджет (ВО):</strong> (11 кл.) по 27 июля, (ССО) по 27 июля.<br>' +
            '• <strong>На платное (ВО):</strong> (11 кл.) по 3 августа, (ССО) по 3 августа.<br>' +
            '<i>Рекомендуем подавать документы заранее, чтобы отслеживать свою позицию в конкурсе!</i>'
    },
    {
        keywords: ['общежитие', 'общага', 'жилье', 'заселение', 'где жить'],
        answer: 'Всем иногородним абитуриентам дневной формы получения образования (как ССО, так и ВО) предоставляется благоустроенное общежитие! Вселяют весь новый набор, далее по заслугам: успеваемость, дисциплина, участие в жизни академии.'
    },
    {
        keywords: ['калькулятор', 'шанс', 'балл', 'как работать', 'позиция', 'поиск', 'как пользоваться'],
        answer: 'Наш интерактивный калькулятор анализирует загруженные данные.<br>' +
            '1. Перейди во вкладку нужного уровня образования (например, ССО после 9 класса).<br>' +
            '2. Введи свой средний балл в строку поиска.<br>' +
            '3. Программа определит твою позицию среди других абитуриентов, уже поданных документы, и подсветит шансы цветом (зеленый — проходишь, желтый — на грани, красный — не проходишь).'
    },
    {
        keywords: ['привет', 'здравствуй', 'добрый день', 'ку', 'хай', 'hello', 'бот'],
        answer: 'Привет! Я виртуальный ассистент приемной комиссии. Готов помочь тебе разобраться в вопросах поступления. О чем бы ты хотел узнать?'
    },
    {
        keywords: ['сокращен', 'сокращенка', 'после колледжа', 'вышка после', 'экзамен', 'предмет', 'испытан', 'внутрен', 'вступительн', 'с каких специальностей'],
        answer: 'Для выпускников колледжей (ССО) в 2026 году открыт прием на сокращенный срок получения общего высшего образования (ВО) на дневную и заочную формы. Максимальный балл по конкурсу на эти специальности равен 300.<br><br>' +
            '<b>ВНУТРЕННИЕ ВСТУПИТЕЛЬНЫЕ ИСПЫТАНИЯ (ПИСЬМЕННО):</b><br>' +
            '• <strong>Математика</strong> (письменно)<br>' +
            '• <strong>Основы информационных технологий</strong> (письменно)<br><br>' +
            '<b>СООТВЕТСТВИЕ СПЕЦИАЛЬНОСТЕЙ ДЛЯ ПОСТУПЛЕНИЯ В 2026 ГОДУ:</b><br><br>' +
            '• <strong>СИСТЕМЫ И СЕТИ ИНФОКОММУНИКАЦИЙ (дневная, заочная)</strong>. Принимаются выпускники ССО, получившие образование по специальностям:<br>' +
            ' — Системы радиосвязи, радиовещания и телевидения;<br>' +
            ' — Сети телекоммуникаций;<br>' +
            ' — Техническая эксплуатация систем радиосвязи, радиовещания и телевидения;<br>' +
            ' — Техническая эксплуатация систем и сетей телекоммуникаций;<br>' +
            ' — Информационные кабельные сети.<br><br>' +
            '• <strong>ПОЧТОВАЯ СВЯЗЬ (дневная, заочная)</strong>. Принимаются выпускники ССО, получившие образование по специальностям:<br>' +
            ' — Почтовая связь;<br>' +
            ' — Почтовая деятельность.<br><br>' +
            '• <strong>ПРИКЛАДНАЯ ИНФОРМАТИКА (дневная, заочная)</strong>. Принимаются выпускники ССО, получившие образование по специальностям:<br>' +
            ' — Тестирование программного обеспечения;<br>' +
            ' — Разработка и сопровождение веб-ресурсов.'
    },
    {
        keywords: ['платн', 'оплат', 'стоимость', 'цена', 'обучение стоит'],
        answer: 'Прием на платной основе открыт на большинство специальностей. Информацию о планах приема и текущем конкурсе ты можешь увидеть, переключив соответствующую вкладку внутри карты интересующей тебя специальности. <br>' +
            '<strong>Стоимость обучения: </strong><br>' +
            '<strong>Уровень ССО (дневная форма): </strong> в год 3030 руб. (в месяц 303 руб.)<br>' +
            '<strong>Уровень ССО (заочная форма): </strong> в год 1132 руб. (в семестр 566 руб.)<br>' +
            '<strong>Уровень ВО (дневная форма): </strong> в год 3520 руб. (в месяц 352 руб.)<br>' +
            '<strong>Уровень ВО (заочная форма): </strong> в год 1636 руб. (в семестр 818 руб.)<br>'
    },
    {
        keywords: ['работает', 'график', 'часы', 'режим', 'время работы', 'воскресен', 'информир', 'обновлен', 'время работы комиссии', 'часы работы', 'режим работы', 'когда работает', 'во сколько работает', 'работы приемной', 'приемка', 'приёмка'],
        answer: '<b>Время работы приемной комиссии:</b><br>' +
            '• Понедельник – Суббота: <b>с 9:00 до 18:00</b>.<br>' +
            '• Воскресенье: выходной день.<br>' +
            '<i>Примечание: Если на воскресенье выпадает первый или последний день приема документов, приемная комиссия будет работать и в воскресенье.</i><br><br>' +
            '<b>График информирования абитуриентов:</b><br>' +
            '• Сведения обновляются ежедневно в <b>12:00, 15:00 и 18:00</b> на официальном сайте и на стендах в холле приемной комиссии.<br>' +
            '• В последний день приема документов обновление информации происходит в <b>10:00, 12:00, 15:00 и 17:00</b> (последнее обновление хода приема).<br>' +
            '• Окончательное информирование осуществляется на следующий день после завершения приема документов <b>не позднее 12:00</b>.'
    }
];

/* Хранилище смещений ячеек Google Таблицы для сверки с базой */
const sso9Specs = [
    { name: "Тестирование программного обеспечения", offset: 148, offsetPaid: 164 },
    { name: "Разработка и сопровождение веб-ресурсов", offset: 116, offsetPaid: 132 },
    { name: "Техническая эксплуатация систем и сетей телекоммуникаций", offset: 180, offsetPaid: 196 },
    { name: "Информационные кабельные сети", offset: 212, offsetPaid: 228 },
    { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", offset: 244, offsetPaid: 260 },
    { name: "Техническая эксплуатация мультимедийных систем", offset: 276, offsetPaid: null },
    { name: "Почтовая деятельность", offset: 292, offsetPaid: 308 }
];

const sso11Specs = [
    { name: "Техническая эксплуатация систем и сетей телекоммуникаций (Дневное)", offset: 356, offsetPaid: 372 },
    { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения (Дневное)", offset: 388, offsetPaid: 404 },
    { name: "Почтовая деятельность (Дневное)", offset: 420, offsetPaid: 436 },
    { name: "Тестирование программного обеспечения (Дневное)", offset: 324, offsetPaid: 340 },
    { name: "Техническая эксплуатация систем и сетей телекоммуникаций (Заочное)", offset: 454, offsetPaid: 470 },
    { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения (Заочное)", offset: 486, offsetPaid: 502 },
    { name: "Почтовая деятельность (Заочное)", offset: 518, offsetPaid: 534 }
];

const voSpecs = [
    { name: "Автоматизация технологических процессов и производств", offset: 32, offsetPaid: null, isVo: true },
    { name: "Системы и сети инфокоммуникаций", offset: 33, offsetPaid: 50, isVo: true },
    { name: "Прикладная информатика", offset: 34, offsetPaid: 51, isVo: true },
    { name: "Цифровые клиентские сервисы и почтово-логистические системы", offset: 35, offsetPaid: null, isVo: true },
    { name: "Маркетинг", offset: 36, offsetPaid: 52, isVo: true }
];

const voSsoSpecs = [
    { name: "Системы и сети инфокоммуникаций (Дневное сокращенное)", offset: 64, offsetPaid: 79, isVo: true, isVoSso: true },
    { name: "Прикладная информатика (Дневное сокращенное)", offset: 66, offsetPaid: 81, isVo: true, isVoSso: true },
    { name: "Почтовая связь (Дневное сокращенное)", offset: 67, offsetPaid: null, isVo: true, isVoSso: true },
    { name: "Системы и сети инфокоммуникаций (Заочное сокращенное)", offset: 93, offsetPaid: 108, isVo: true, isVoSso: true },
    { name: "Почтовая связь (Заочное сокращенное)", offset: 96, offsetPaid: 111, isVo: true, isVoSso: true }
];

const ASSISTANT_SHEET_ID = '1uFwZs-jzJiUkZk6U266bo4QbmwjAjoUcc0pKAabWhos';
const ASSISTANT_XLSX_URL = `https://docs.google.com/spreadsheets/d/${ASSISTANT_SHEET_ID}/export?format=xlsx`;
let assistantWorkbook = null;


/* ==========================================================================
   БЛОК 2: АСИНХРОННАЯ ЗАГРУЗКА И ИНИЦИАЛИЗАЦИЯ EXCEL (SHEETJS)
   ========================================================================== */

/* БАЗОВАЯ ОПТИМИЗАЦИЯ ВЕБ-СТРАНИЦ (PERFORMANCE, SEO): Динамическая отложенная загрузка тяжелой внешней библиотеки XLSX при первом открытии чата */
function ensureXlsxLoaded(callback) {
    if (typeof XLSX !== 'undefined') {
        callback();
        return;
    }
    const script = document.createElement('script');
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
    script.onload = callback;
    document.head.appendChild(script);
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Сетевой fetch-запрос к Google API для импорта конкурсной таблицы */
function initAssistantDatabase() {
    ensureXlsxLoaded(() => {
        fetch(ASSISTANT_XLSX_URL)
            .then(res => {
                if (res.ok) return res.arrayBuffer();
                throw new Error();
            })
            .then(buffer => {
                assistantWorkbook = XLSX.read(buffer, { type: 'array' });
                console.log("Интерактивная база данных ассистента успешно загружена.");
            })
            .catch(err => {
                console.error("Ошибка загрузки данных.", err);
            });
    });
}


/* ==========================================================================
   БЛОК 3: ПАРСИНГ, ГРУППИРОВКА И ОБРАБОТКА ДАННЫХ КОНКУРСА
   ========================================================================== */

function getCell(sheet, r, c) {
    if (!sheet) return '';
    const addr = XLSX.utils.encode_cell({ r, c });
    return sheet[addr] ? sheet[addr].v : '';
}

function getGroupedPlans(sheet, currentOffset) {
    let startRow = currentOffset;
    // Лимиты, чтобы не уйти в чужой блок при поиске объединенных ячеек
    const limitRow = currentOffset >= 90 ? 93 : 64;

    while (startRow > limitRow && getCell(sheet, startRow, 6) === "") {
        startRow--;
    }

    let totalPlan = 0;
    let endRow = startRow;

    while (endRow < 1000) {
        totalPlan += parseInt(getCell(sheet, endRow, 4), 10) || 0;

        const nextTotalVal = getCell(sheet, endRow + 1, 6);
        const nextName = getCell(sheet, endRow + 1, 3);

        if (nextTotalVal !== "" || nextName === "") {
            break;
        }
        endRow++;
    }

    return {
        sumPlan: totalPlan,
        dataRow: startRow
    };
}

function parseSsoBlock(sheet, offset) {
    const plan = parseInt(getCell(sheet, offset + 10, 2), 10) || 0;
    let applications = [];
    for (let col = 4, score = 10.0; col <= 74; col++, score = +(score - 0.1).toFixed(1)) {
        let count = parseInt(getCell(sheet, offset + 10, col), 10) || 0;
        if (count > 0) applications.push({ score: +score.toFixed(1), count });
    }
    return { plan, applications };
}

function parseVoBlock(sheet, offset, isVoSso) {
    let plan = 0;
    let mainRow = offset;

    // Для Сокращенной формы (ССО) нужна группировка, для Полной (11 кл) - читаем напрямую
    if (isVoSso) {
        const groupInfo = getGroupedPlans(sheet, offset);
        plan = groupInfo.sumPlan;
        mainRow = groupInfo.dataRow;
    } else {
        plan = parseInt(getCell(sheet, offset, 4), 10) || 0;
    }

    let applications = [];
    let startCol = 11;
    let currentMax = isVoSso ? 300 : 400;
    const h1 = isVoSso ? 63 : 31;
    const h2 = isVoSso ? 62 : 30;

    for (let col = startCol; col <= 100; col++) {
        let count = parseInt(getCell(sheet, mainRow, col), 10) || 0;
        let currentMin = currentMax - 4;
        let headerVal = getCell(sheet, h1, col) || getCell(sheet, h2, col);

        if (!headerVal && count === 0 && currentMax < (isVoSso ? 250 : 350)) {
            break;
        }
        if (count > 0) {
            applications.push({ score: currentMax, minScore: currentMin, count });
        }
        currentMax -= 5;
        if (currentMax < 0) break;
    }
    return { plan, applications };
}


/* ==========================================================================
   БЛОК 4: АЛГОРИТМЫ ОПРЕДЕЛЕНИЯ ПОЗИЦИЙ И ПРОХОДНОГО БАЛЛА
   ========================================================================== */

function getSsoPosition(applications, userScore) {
    const count = applications
        .filter(app => app.score >= userScore)
        .reduce((sum, app) => sum + app.count, 0);
    return count + 1;
}

function getVoPosition(applications, userScore) {
    let countAhead = 0;
    applications.forEach(app => {
        if (userScore < app.minScore) {
            countAhead += app.count;
        } else if (userScore >= app.minScore && userScore <= app.score) {
            countAhead += app.count;
        }
    });
    return countAhead + 1;
}

function getPassingScore(blockData, isVo) {
    let allScores = [];

    if (isVo) {
        blockData.applications.forEach(app => {
            for (let i = 0; i < app.count; i++) {
                allScores.push(app.minScore);
            }
        });
    } else {
        blockData.applications.forEach(app => {
            for (let i = 0; i < app.count; i++) {
                allScores.push(app.score);
            }
        });
    }

    allScores.sort((a, b) => b - a);

    if (allScores.length === 0) return "Нет заявлений";
    if (blockData.plan === 0) return "Нет бюджетных мест";

    if (allScores.length < blockData.plan) {
        const lowest = allScores[allScores.length - 1];
        return isVo ? `${lowest}+ (места свободны)` : `${lowest.toFixed(1)} (места свободны)`;
    } else {
        const cutoff = allScores[blockData.plan - 1];
        return isVo ? `${cutoff}` : `${cutoff.toFixed(1)}`;
    }
}


/* ==========================================================================
   БЛОК 5: ПОИСКОВЫЕ КЛЮЧЕВЫЕ АЛГОРИТМЫ И СВЕРКА ВВОДА
   ========================================================================== */

function findMatchingSpecialties(text) {
    const allSpecs = [
        ...sso9Specs.map(s => ({ ...s, category: 'ССО (после 9 кл.)', parser: parseSsoBlock, isVo: false, isVoSso: false })),
        ...sso11Specs.map(s => ({ ...s, category: 'ССО (после 11 кл.)', parser: parseSsoBlock, isVo: false, isVoSso: false })),
        ...voSpecs.map(s => ({ ...s, category: 'ВО (11 кл.)', parser: parseVoBlock, isVo: true, isVoSso: false })),
        ...voSsoSpecs.map(s => ({ ...s, category: 'ВО после ССО (сокращенная)', parser: parseVoBlock, isVo: true, isVoSso: true }))
    ];

    const specKeywords = [
        { pattern: /веб|web|ресурс/i, key: "web" },
        { pattern: /тестир|тест|тпо|qa|софт/i, key: "test" },
        { pattern: /кабель|икс/i, key: "cable" },
        { pattern: /мультимеди/i, key: "multi" },
        { pattern: /почт/i, key: "post" },
        { pattern: /радио|вещ|телевиден/i, key: "radio" },
        { pattern: /телеком|сеть|коммун|инфоком/i, key: "telecom" },
        { pattern: /автоматиз/i, key: "auto" },
        { pattern: /информатик/i, key: "info" },
        { pattern: /маркетинг/i, key: "marketing" }
    ];

    let matchedSpecs = [];
    specKeywords.forEach(k => {
        if (k.pattern.test(text)) {
            allSpecs.forEach(spec => {
                let isMatch = false;
                if (k.key === "web" && /веб|ресурс/i.test(spec.name)) isMatch = true;
                if (k.key === "test" && /тестир|тест/i.test(spec.name)) isMatch = true;
                if (k.key === "cable" && /кабель/i.test(spec.name)) isMatch = true;
                if (k.key === "multi" && /мультимеди/i.test(spec.name)) isMatch = true;
                if (k.key === "post" && /почт|связь/i.test(spec.name)) {
                    if (!/радио/i.test(spec.name)) isMatch = true;
                }
                if (k.key === "auto" && /автоматиз/i.test(spec.name)) isMatch = true;
                if (k.key === "info" && /информатик/i.test(spec.name)) isMatch = true;
                if (k.key === "marketing" && /маркетинг/i.test(spec.name)) isMatch = true;
                if (k.key === "telecom" && /телеком|инфоком/i.test(spec.name)) isMatch = true;
                if (k.key === "radio" && /радио|вещ|телевиден/i.test(spec.name)) isMatch = true;

                if (isMatch && !matchedSpecs.some(m => m.offset === spec.offset && m.category === spec.category)) {
                    matchedSpecs.push(spec);
                }
            });
        }
    });

    return matchedSpecs;
}

function matchesKeyword(text, keyword) {
    const textLower = text.toLowerCase();
    const kwLower = keyword.toLowerCase();

    if (kwLower.length <= 3) {
        const regex = new RegExp(`\\b${kwLower}\\b`, 'i');
        return regex.test(textLower);
    }
    return textLower.includes(kwLower);
}


/* ==========================================================================
   БЛОК 6: ВЗАИМОДЕЙСТВИЕ С ИНТЕРФЕЙСОМ ЧАТА И DOM-МАНИПУЛЯЦИИ
   ========================================================================== */

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Управление видимостью виджета чата в окне браузера */
function toggleAssistant() {
    const windowEl = document.getElementById('ai-window');
    const isHidden = windowEl.style.display === 'none';
    windowEl.style.display = isHidden ? 'flex' : 'none';

    if (isHidden) {
        const userInput = document.getElementById('ai-user-input');
        if (userInput) {
            userInput.focus();
        }
        if (!assistantWorkbook) {
            initAssistantDatabase();
        }
    }
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (СЛАЙДЕРЫ, ФОРМЫ, ФИЛЬТРЫ) С ОБРАБОТКОЙ ДАННЫХ ПОЛЬЗОВАТЕЛЯ: Обработка быстрых вопросов с плашек */
function sendQuickQuestion(questionText) {
    appendMessage(questionText, 'user');
    generateBotResponse(questionText);
    hideQuickQuestions();
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (СЛАЙДЕРЫ, ФОРМЫ, ФИЛЬТРЫ) С ОБРАБОТКОЙ ДАННЫХ ПОЛЬЗОВАТЕЛЯ: Считывание сообщений из инпута ввода */
function sendMessageFromInput() {
    const inputEl = document.getElementById('ai-user-input');
    const text = inputEl.value.trim();
    if (!text) return;

    appendMessage(text, 'user');
    inputEl.value = '';
    generateBotResponse(text);
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Перехват нажатия Enter для отправки сообщений */
function handleAssistantKey(e) {
    if (e.key === 'Enter') {
        sendMessageFromInput();
    }
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Генерация HTML-ноды сообщения и автопрокрутка списка сообщений */
function appendMessage(text, sender) {
    const messagesContainer = document.getElementById('ai-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `ai-message ${sender}`;

    // Если пишет пользователь — выводим как безопасный текст (блокирует выполнение XSS-скриптов)
    // Если отвечает бот — разрешаем innerHTML для поддержки тегов разметки и ссылок
    if (sender === 'user') {
        msgDiv.textContent = text;
    } else {
        msgDiv.innerHTML = text;
    }

    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

/* ==========================================================================
   БЛОК 7: ГЕНЕРАТОР ДИНАМИЧЕСКИХ ОТВЕТОВ БОТА
   ========================================================================== */

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (СЛАЙДЕРЫ, ФОРМЫ, ФИЛЬТРЫ) С ОБРАБОТКОЙ ДАННЫХ ПОЛЬЗОВАТЕЛЯ: Расчет шансов на основе введенного балла */
function handleScoreCalculation(userScore, isVoScore, originalText) {
    if (!assistantWorkbook) {
        initAssistantDatabase();
        setTimeout(() => {
            generateBotResponse(originalText);
        }, 1200);
        appendMessage('Секунду, я загружаю актуальную базу данных конкурса, чтобы рассчитать ваши шансы...', 'bot');
        return;
    }

    try {
        const sheet = assistantWorkbook.Sheets[assistantWorkbook.SheetNames[0]];
        let responseHtml = '';

        if (isVoScore) {
            responseHtml = `<strong>Высшее образование ВО (11 классов)</strong> с баллом <strong>${userScore}</strong>:<br><br>`;
            voSpecs.forEach((spec, index) => {
                const budgetData = parseVoBlock(sheet, spec.offset, false);
                const budgetPos = getVoPosition(budgetData.applications, userScore);
                const budgetStatus = budgetPos <= budgetData.plan
                    ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                    : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';

                let paidHtml = '';
                if (spec.offsetPaid) {
                    const paidData = parseVoBlock(sheet, spec.offsetPaid, false);
                    // ИСПРАВЛЕНИЕ: передаем paidData.applications вместо budgetData.applications
                    const paidPos = getVoPosition(paidData.applications, userScore);
                    const paidStatus = paidPos <= paidData.plan
                        ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                        : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';
                    paidHtml = `  - Платно: ${paidPos} из ${paidData.plan} мест (${paidStatus})<br>`;
                } else {
                    paidHtml = `  - Платно: прием не осуществляется<br>`;
                }

                responseHtml += `${index + 1}. <strong>${spec.name}:</strong><br>` +
                    `  - Бюджет: ${budgetPos} из ${budgetData.plan} мест (${budgetStatus})<br>` +
                    paidHtml + `<br>`;
            });

            if (userScore <= 300) {
                responseHtml += `<strong>ВО на базе ССО (Сокращенная форма)</strong> с баллом <strong>${userScore}</strong>:<br><br>`;
                voSsoSpecs.forEach((spec, index) => {
                    const budgetData = parseVoBlock(sheet, spec.offset, true);
                    const budgetPos = getVoPosition(budgetData.applications, userScore);
                    const budgetStatus = budgetPos <= budgetData.plan
                        ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                        : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';

                    let paidHtml = '';
                    if (spec.offsetPaid) {
                        const paidData = parseVoBlock(sheet, spec.offsetPaid, true);
                        // ИСПРАВЛЕНИЕ: передаем paidData.applications вместо budgetData.applications
                        const paidPos = getVoPosition(paidData.applications, userScore);
                        const paidStatus = paidPos <= paidData.plan
                            ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                            : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';
                        paidHtml = `  - Платно: ${paidPos} из ${paidData.plan} мест (${paidStatus})<br>`;
                    } else {
                        paidHtml = `  - Платно: прием не осуществляется<br>`;
                    }

                    responseHtml += `${index + 1}. <strong>${spec.name}:</strong><br>` +
                        `  - Бюджет: ${budgetPos} из ${budgetData.plan} мест (${budgetStatus})<br>` +
                        paidHtml + `<br>`;
                });
            }
        } else {
            responseHtml = `<strong>База 9 классов ССО</strong> с вашим баллом <strong>${userScore}</strong>:<br><br>`;
            sso9Specs.forEach((spec, index) => {
                const budgetData = parseSsoBlock(sheet, spec.offset);
                const budgetPos = getSsoPosition(budgetData.applications, userScore);
                const budgetStatus = budgetPos <= budgetData.plan
                    ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                    : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';

                let paidHtml = '';
                if (spec.offsetPaid) {
                    const paidData = parseSsoBlock(sheet, spec.offsetPaid);
                    // ИСПРАВЛЕНИЕ: здесь была похожая ошибка, исправляем для надежности
                    const paidPos = getSsoPosition(paidData.applications, userScore);
                    const paidStatus = paidPos <= paidData.plan
                        ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                        : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';
                    paidHtml = `  - Платно: ${paidPos} из ${paidData.plan} мест (${paidStatus})<br>`;
                } else {
                    paidHtml = `  - Платно: прием не осуществляется<br>`;
                }

                responseHtml += `${index + 1}. <strong>${spec.name}:</strong><br>` +
                    `  - Бюджет: ${budgetPos} из ${budgetData.plan} мест (${budgetStatus})<br>` +
                    paidHtml + `<br>`;
            });

            responseHtml += `<strong>База 11 классов ССО (дневное)</strong>:<br><br>`;
            sso11Specs.forEach((spec, index) => {
                const budgetData = parseSsoBlock(sheet, spec.offset);
                const budgetPos = getSsoPosition(budgetData.applications, userScore);
                const budgetStatus = budgetPos <= budgetData.plan
                    ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                    : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';

                let paidHtml = '';
                if (spec.offsetPaid) {
                    const paidData = parseSsoBlock(sheet, spec.offsetPaid);
                    const paidPos = getSsoPosition(paidData.applications, userScore);
                    const paidStatus = paidPos <= paidData.plan
                        ? '<span style="color: #2e7d32; font-weight: bold;">Проходите</span>'
                        : '<span style="color: #c62828; font-weight: bold;">Не проходите</span>';
                    paidHtml = `  - Платно: ${paidPos} из ${paidData.plan} мест (${paidStatus})<br>`;
                } else {
                    paidHtml = `  - Платно: прием не осуществляется<br>`;
                }

                responseHtml += `${index + 1}. <strong>${spec.name}:</strong><br>` +
                    `  - Бюджет: ${budgetPos} из ${budgetData.plan} мест (${budgetStatus})<br>` +
                    paidHtml + `<br>`;
            });
        }

        setTimeout(() => {
            appendMessage(responseHtml, 'bot');
        }, 300);
    } catch (e) {
        console.error(e);
        appendMessage('Произошла ошибка при расчете позиций.', 'bot');
    }
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (СЛАЙДЕРЫ, ФОРМЫ, ФИЛЬТРЫ) С ОБРАБОТКОЙ ДАННЫХ ПОЛЬЗОВАТЕЛЯ: Считывание текущих проходных баллов */
function handlePassingScoreQuery(normalizedText, originalText) {
    if (!assistantWorkbook) {
        initAssistantDatabase();
        setTimeout(() => {
            generateBotResponse(originalText);
        }, 1200);
        appendMessage('Секунду, я загружаю актуальную базу данных конкурса, чтобы узнать текущие проходные баллы...', 'bot');
        return;
    }

    try {
        const sheet = assistantWorkbook.Sheets[assistantWorkbook.SheetNames[0]];
        const matchedSpecs = findMatchingSpecialties(normalizedText);

        if (matchedSpecs.length > 0) {
            let reply = 'Актуальный проходной балл на данный момент:<br><br>';
            matchedSpecs.forEach(spec => {
                const budgetBlock = spec.isVo ? parseVoBlock(sheet, spec.offset, spec.isVoSso) : parseSsoBlock(sheet, spec.offset);
                const budgetPassing = getPassingScore(budgetBlock, spec.isVo);

                let paidPassing = "прием не осуществляется";
                if (spec.offsetPaid) {
                    const paidBlock = spec.isVo ? parseVoBlock(sheet, spec.offsetPaid, spec.isVoSso) : parseSsoBlock(sheet, spec.offsetPaid);
                    paidPassing = getPassingScore(paidBlock, spec.isVo);
                }

                reply += `• <strong>${spec.name}</strong> (${spec.category}):<br>` +
                    `  - Бюджет: <strong>${budgetPassing}</strong><br>` +
                    `  - Платно: <strong>${paidPassing}</strong><br><br>`;
            });
            reply += `<i>Примечание: Проходной балл формируется динамически на основе поданных заявлений и меняется каждый день.</i>`;
            appendMessage(reply, 'bot');
        } else {
            let reply = 'На данный момент (ССО, после 9 классов) складываются следующие проходные баллы:<br><br>';
            sso9Specs.forEach((spec, index) => {
                const budgetBlock = parseSsoBlock(sheet, spec.offset);
                const budgetPassing = getPassingScore(budgetBlock, false);

                let paidPassing = "прием не осуществляется";
                if (spec.offsetPaid) {
                    const paidBlock = parseSsoBlock(sheet, spec.offsetPaid);
                    paidPassing = getPassingScore(paidBlock, false);
                }

                reply += `${index + 1}. <strong>${spec.name}:</strong><br>` +
                    `   - Бюджет: <strong>${budgetPassing}</strong><br>` +
                    `   - Платно: <strong>${paidPassing}</strong><br><br>`;
            });
            reply += `<i>Чтобы узнать балл на ВО или ССО (11 кл.), напишите название конкретной специальности (например: "какой балл на прикладную информатику").</i>`;
            appendMessage(reply, 'bot');
        }
    } catch (e) {
        console.error(e);
        appendMessage('Не удалось выполнить расчет проходных баллов.', 'bot');
    }
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (СЛАЙДЕРЫ, ФОРМЫ, ФИЛЬТРЫ) С ОБРАБОТКОЙ ДАННЫХ ПОЛЬЗОВАТЕЛЯ: Сверка ключевых слов с вводом и выбор функции ответа */
function generateBotResponse(userText) {
    const textLower = userText.toLowerCase();
    const normalizedText = textLower.replace(',', '.');

    // Проверяем, спрашивает ли пользователь про текущие проходные баллы
    const isAskingForCutoff = /проходн|какой балл|какие балл|балл.*выходит|балл.*сейчас/i.test(normalizedText);
    if (isAskingForCutoff) {
        handlePassingScoreQuery(normalizedText, userText);
        return;
    }

    let bestMatch = null;
    let maxScore = 0;

    // Ищем наиболее подходящий ответ в базе знаний ассистента
    for (const item of assistantDatabase) {
        let currentScore = 0;
        for (const keyword of item.keywords) {
            if (matchesKeyword(normalizedText, keyword)) {
                currentScore += 1;
            }
        }
        if (currentScore > maxScore) {
            maxScore = currentScore;
            bestMatch = item.answer;
        }
    }

    if (bestMatch && maxScore > 0) {
        setTimeout(() => {
            appendMessage(bestMatch, 'bot');
        }, 400);
        return;
    }

    // Дефолтный ответ, из которого убрано упоминание ввода баллов
    const defaultReply = 'Я не до конца понял твой вопрос. Попробуй спросить подробнее, используя ключевые слова, например: <strong>документы</strong>, <strong>сроки подачи</strong>, <strong>общежитие</strong>, <strong>стоимость обучения</strong> или <strong>время работы</strong> приемной комиссии.<br><br>' +
        'Или вы можете обратиться за помощью в официальные телеграм-каналы для абитуриентов:<br>' +
        '• По вопросам ВО: <a href="https://t.me/+v4NV9J9rqqg5OTgy" target="_blank" style="color: #0088cc; font-weight: bold; text-decoration: underline;">https://t.me/+v4NV9J9rqqg5OTgy</a><br>' +
        '• По вопросам ССО: <a href="https://t.me/+v-EXEwGcWasxZTdi" target="_blank" style="color: #0088cc; font-weight: bold; text-decoration: underline;">https://t.me/+v-EXEwGcWasxZTdi</a>';
    setTimeout(() => {
        appendMessage(defaultReply, 'bot');
    }, 400);
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Управление анимацией и видимостью панели быстрых плашек */
function showQuickQuestions() {
    const quickQuestions = document.getElementById('ai-quick-questions');
    if (quickQuestions) {
        quickQuestions.classList.add('visible');

        setTimeout(() => {
            const messagesContainer = document.getElementById('ai-messages');
            if (messagesContainer) {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        }, 260);
    }
}

/* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Скрытие плашек быстрого выбора */
function hideQuickQuestions() {
    const quickQuestions = document.getElementById('ai-quick-questions');
    if (quickQuestions) {
        quickQuestions.classList.remove('visible');
    }
}


/* ==========================================================================
   БЛОК 8: ИНТЕРАКТИВНОЕ УПРАВЛЕНИЕ ОКНОМ С ПОМОЩЬЮ JQUERY UI И КЛИКАМИ
   ========================================================================== */

/* ИСПОЛЬЗОВАНИЕ JQUERY UI / BOOTSTRAP: Инициализация Drag-and-Drop и Resizable перемещения за шапку чата */
$(document).ready(function () {
    const $win = $("#ai-window");

    if ($win.length) {
        $win.draggable({
            handle: ".ai-header",
            containment: "window",
            scroll: false,
            start: function (event, ui) {
                $(this).css({
                    bottom: 'auto',
                    right: 'auto'
                });
            }
        });

        $win.resizable({
            minWidth: 280,
            minHeight: 350,
            maxWidth: 600,
            maxHeight: 800,
            handles: "n, e, s, w, ne, se, sw, nw"
        });
    }

    /* ДОБАВЛЕНИЕ ИНТЕРАКТИВНОСТИ ПРИ ПОМОЩИ BOM/DOM: Глобальный обработчик жестов и кликов для автоматического закрытия быстрых вопросов */
    const handleGlobalInteraction = (e) => {
        const userInput = document.getElementById('ai-user-input');
        const quickQuestions = document.getElementById('ai-quick-questions');
        const aiWindow = document.getElementById('ai-window');

        if (!aiWindow || aiWindow.style.display === 'none') return;

        if (userInput && userInput.contains(e.target)) {
            showQuickQuestions();
            return;
        }

        if (quickQuestions && quickQuestions.contains(e.target)) {
            return;
        }

        hideQuickQuestions();
    };

    document.addEventListener('click', handleGlobalInteraction, true);
    document.addEventListener('touchstart', handleGlobalInteraction, { capture: true, passive: true });
});