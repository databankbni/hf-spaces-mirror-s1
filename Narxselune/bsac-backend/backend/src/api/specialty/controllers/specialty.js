'use strict';

const { createCoreController } = require('@strapi/strapi').factories;
const XLSX = require('xlsx');

const SHEET_ID = '1uFwZs-jzJiUkZk6U266bo4QbmwjAjoUcc0pKAabWhos';
const XLSX_URL = `https://docs.google.com/spreadsheets/d/${SHEET_ID}/export?format=xlsx`;

const parsingConfig = [
  // --- ССО на базе 9 классов (sso9) ---
  { name: "Разработка и сопровождение веб-ресурсов", level: "sso9", form: "dnev", category: "budget" },
  { name: "Разработка и сопровождение веб-ресурсов", level: "sso9", form: "dnev", category: "paid" },
  { name: "Тестирование программного обеспечения", level: "sso9", form: "dnev", category: "budget" },
  { name: "Тестирование программного обеспечения", level: "sso9", form: "dnev", category: "paid" },
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso9", form: "dnev", category: "budget" },
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso9", form: "dnev", category: "paid" },
  { name: "Информационные кабельные сети", level: "sso9", form: "dnev", category: "budget" },
  { name: "Информационные кабельные сети", level: "sso9", form: "dnev", category: "paid" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso9", form: "dnev", category: "budget" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso9", form: "dnev", category: "paid" },
  { name: "Техническая эксплуатация мультимедийных систем", level: "sso9", form: "dnev", category: "budget" },
  { name: "Техническая эксплуатация мультимедийных систем", level: "sso9", form: "dnev", category: "paid" },
  { name: "Почтовая деятельность", level: "sso9", form: "dnev", category: "budget" },
  { name: "Почтовая деятельность", level: "sso9", form: "dnev", category: "paid" },

  // --- ССО на базе 11 классов (sso11) ---
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso11", form: "dnev", category: "budget" },
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso11", form: "dnev", category: "paid" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso11", form: "dnev", category: "budget" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso11", form: "dnev", category: "paid" },
  { name: "Почтовая деятельность", level: "sso11", form: "dnev", category: "budget" },
  { name: "Почтовая деятельность", level: "sso11", form: "dnev", category: "paid" },
  { name: "Тестирование программного обеспечения", level: "sso11", form: "dnev", category: "budget" },
  { name: "Тестирование программного обеспечения", level: "sso11", form: "dnev", category: "paid" },

  // --- ССО Заочное отделение (sso11 zaoch) ---
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso11", form: "zaoch", category: "budget" },
  { name: "Техническая эксплуатация систем и сетей телекоммуникаций", level: "sso11", form: "zaoch", category: "paid" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso11", form: "zaoch", category: "budget" },
  { name: "Техническая эксплуатация систем радиосвязи, радиовещания и телевидения", level: "sso11", form: "zaoch", category: "paid" },
  { name: "Почтовая деятельность", level: "sso11", form: "zaoch", category: "budget" },
  { name: "Почтовая деятельность", level: "sso11", form: "zaoch", category: "paid" },

  // --- ССО на базе ПТО (ssopto) ---
  { name: "Почтовая деятельность", level: "ssopto", form: "zaoch", category: "budget" },

  // --- ВО на базе 11 классов (vo11) ---
  { name: "Автоматизация технологических процессов и производств", level: "vo11", form: "dnev", category: "budget", isVo: true },
  { name: "Системы и сети инфокоммуникаций", level: "vo11", form: "dnev", category: "budget", isVo: true },
  { name: "Системы и сети инфокоммуникаций", level: "vo11", form: "dnev", category: "paid", isVo: true },
  { name: "Прикладная информатика", level: "vo11", form: "dnev", category: "budget", isVo: true },
  { name: "Прикладная информатика", level: "vo11", form: "dnev", category: "paid", isVo: true },
  { name: "Цифровые клиентские сервисы и почтово-логистические системы", level: "vo11", form: "dnev", category: "budget", isVo: true },
  { name: "Маркетинг", level: "vo11", form: "dnev", category: "budget", isVo: true },
  { name: "Маркетинг", level: "vo11", form: "dnev", category: "paid", isVo: true },

  // --- ВО на базе ССО (vosso) ---
  { name: "Системы и сети инфокоммуникаций", level: "vosso", form: "dnev", category: "budget", isVo: true, isVoSso: true },
  { name: "Системы и сети инфокоммуникаций", level: "vosso", form: "dnev", category: "paid", isVo: true, isVoSso: true },
  { name: "Прикладная информатика", level: "vosso", form: "dnev", category: "budget", isVo: true, isVoSso: true },
  { name: "Прикладная информатика", level: "vosso", form: "dnev", category: "paid", isVo: true, isVoSso: true },
  { name: "Почтовая связь", level: "vosso", form: "dnev", category: "budget", isVo: true, isVoSso: true },
  { name: "Системы и сети инфокоммуникаций", level: "vosso", form: "zaoch", category: "budget", isVo: true, isVoSso: true },
  { name: "Системы и сети инфокоммуникаций", level: "vosso", form: "zaoch", category: "paid", isVo: true, isVoSso: true },
  { name: "Почтовая связь", level: "vosso", form: "zaoch", category: "budget", isVo: true, isVoSso: true },
  { name: "Почтовая связь", level: "vosso", form: "zaoch", category: "paid", isVo: true, isVoSso: true },
  { name: "Прикладная информатика", level: "vosso", form: "zaoch", category: "budget", isVo: true, isVoSso: true },
  { name: "Прикладная информатика", level: "vosso", form: "zaoch", category: "paid", isVo: true, isVoSso: true }
];

function getVal(sheet, r, c) {
  const addr = XLSX.utils.encode_cell({ r, c });
  return sheet[addr] ? sheet[addr].v : '';
}

// Поиск строки заголовка баллов для ВО (поиск 400 или 300 вверх от строки специальности)
function findVoHeaderRow(sheet, dataRow, isVoSso) {
  const targetScore = isVoSso ? 300 : 400;
  for (let r = dataRow - 1; r >= 0; r--) {
    const val1 = parseInt(getVal(sheet, r, 11), 10);
    const val2 = parseInt(getVal(sheet, r, 12), 10);
    if (val1 === targetScore || val2 === targetScore) {
      return r;
    }
  }
  return isVoSso ? 63 : 31;
}

// Вычисление планов объединенных ячеек для сокращенного ВО
function getGroupedPlans(sheet, startRow, specName) {
  let totalPlan = 0;
  let endRow = startRow;
  const target = specName.toLowerCase().replace(/[^a-zа-я0-9]/g, '');

  while (endRow < 1000) {
    const currentName = getVal(sheet, endRow, 3).toString().toLowerCase().replace(/[^a-zа-я0-9]/g, ''); // Столбец D (3)
    if (currentName.includes(target)) {
      totalPlan += parseInt(getVal(sheet, endRow, 4), 10) || 0; // Столбец E (4)
      endRow++;
    } else {
      break;
    }
  }
  return { sumPlan: totalPlan, startRow, endRow: endRow - 1 };
}

// Универсальный алгоритм контекстного поиска (Безопасная версия без наложения таблиц)
function findAnchorRow(sheet, level, form, category, specName) {
  const range = XLSX.utils.decode_range(sheet['!ref']);

  // Очищаем искомое имя от пробелов, дефисов и переносов строк для 100% совпадения
  const targetSpecClean = specName.toLowerCase().replace(/[^a-zа-я0-9]/g, '');

  const isPaid = category === 'paid';
  const catKeyword = isPaid ? 'плат' : 'бюджет';
  const formKeyword = form === 'zaoch' ? 'заоч' : 'днев';

  let levelKeyword = '';
  if (level === 'sso9') levelKeyword = 'базов';
  else if (level === 'sso11') levelKeyword = 'общего средн';
  else if (level === 'ssopto') levelKeyword = 'профес';
  else if (level === 'vo11') levelKeyword = 'полн';
  else if (level === 'vosso') levelKeyword = 'сокращ';

  // Сканируем весь лист от начала до конца в поисках строк с названием специальности
  for (let r = 0; r <= range.e.r; r++) {
    let isSpecMatch = false;

    // Проверяем наличие специальности, предварительно очистив текст ячейки
    for (let col = 0; col <= 15; col++) {
      const val = getVal(sheet, r, col)?.toString().toLowerCase() || '';
      if (val) {
        const cleanVal = val.replace(/[^a-zа-я0-9]/g, '');
        if (cleanVal.includes(targetSpecClean)) {
          isSpecMatch = true;
          break;
        }
      }
    }

    // Если нашли название специальности, проверяем шапку НАД ней (строго до 15 строк вверх)
    if (isSpecMatch) {
      let upperContext = '';
      const startUp = Math.max(0, r - 15); // Стабильное и безопасное окно в 15 строк

      for (let upR = startUp; upR < r; upR++) {
        for (let col = 0; col <= 15; col++) {
          upperContext += ' ' + getVal(sheet, upR, col).toString().toLowerCase();
        }
      }

      // Проверяем уровень образования (для ПТО делаем мягкую проверку на синонимы)
      let hasLevel = false;
      if (level === 'ssopto') {
        hasLevel = upperContext.includes('профес') || upperContext.includes('пто');
      } else {
        hasLevel = upperContext.includes(levelKeyword);
      }

      const hasForm = upperContext.includes(formKeyword);
      const hasCat = upperContext.includes(catKeyword);

      let isValidContext = hasLevel && hasForm && hasCat;

      // --- ХИРУРГИЧЕСКИЕ ИСКЛЮЧЕНИЯ (БЕЗ РИСКА НАЛОЖЕНИЯ) ---

      // 1. Защита от пересечений полного и сокращенного ВО
      if (level === 'vo11' && upperContext.includes('сокращен')) isValidContext = false;
      if (level === 'vosso' && !upperContext.includes('сокращен')) isValidContext = false;

      // 2. Исключаем попадание ПТО в блок ССО 11 классов
      if (level === 'sso11' && upperContext.includes('профес')) isValidContext = false;

      if (isValidContext) {
        return r;
      }
    }
  }

  return -1; // Если специальность не найдена
}

module.exports = createCoreController('api::specialty.specialty', ({ strapi }) => ({
  async parseExcel(ctx) {
    try {
      const response = await fetch(XLSX_URL);
      if (!response.ok) throw new Error("Не удалось загрузить Google Таблицу");
      const buffer = await response.arrayBuffer();

      const workbook = XLSX.read(buffer, { type: 'array' });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];

      let updatedCount = 0;

      for (const config of parsingConfig) {
        // Ищем строку специальности на листе
        let anchorRow = findAnchorRow(sheet, config.level, config.form, config.category, config.name);

        let plan = 0;
        let total = 0;

        // Защита калькуляторов: инициализируем распределение пустыми массивами по умолчанию
        let distribution = { common: [], lgota: [], target: [] };

        // Если специальность НЕ НАЙДЕНА на листе, мы НЕ пропускаем ее, 
        // а принудительно обнуляем в базе, чтобы на сайте загорелась плашка "Набор не осуществляется"
        if (anchorRow === -1) {
          strapi.log.warn(
            `[Парсер] Специальность "${config.name}" (${config.level}, ${config.category}) не найдена. Устанавливаем план = 0.`
          );
        } else {
          const dataRow = anchorRow;
          let groupInfo = { startRow: dataRow, endRow: dataRow, sumPlan: 0 };

          if (config.isVo) {
            if (config.isVoSso) {
              groupInfo = getGroupedPlans(sheet, dataRow, config.name);
              plan = groupInfo.sumPlan;
            } else {
              plan = parseInt(getVal(sheet, dataRow, 4), 10) || 0;
              groupInfo = { startRow: dataRow, endRow: dataRow };
            }

            // Считываем Всего заявлений строго с первой строки объединенной группы
            total = parseInt(getVal(sheet, groupInfo.startRow, 6), 10) || 0;

            let currentMax = config.isVoSso ? 300 : 400;
            const headerRowIndex = findVoHeaderRow(sheet, dataRow, config.isVoSso);

            const commonDist = [];
            const maxCols = config.isVoSso ? 51 : 71;

            for (let col = 11; col <= maxCols; col++) {
              let count = 0;
              for (let r = groupInfo.startRow; r <= groupInfo.endRow; r++) {
                count += parseInt(getVal(sheet, r, col), 10) || 0;
              }

              if (count > 0) {
                commonDist.push({ score: currentMax, count });
              }
              currentMax -= 5;
            }

            // Структура для ВО: общий конкурс и суммарные метаданные по целевикам и льготникам
            distribution = {
              common: commonDist,
              lgota: [],
              target: [],
              targetTotal: parseInt(getVal(sheet, dataRow, 7), 10) || 0,
              noExamsTotal: parseInt(getVal(sheet, dataRow, 8), 10) || 0,
              outOfCompetitionTotal: parseInt(getVal(sheet, dataRow, 9), 10) || 0
            };
          } else {
            plan = parseInt(getVal(sheet, dataRow, 2), 10) || 0;
            const planTarget = parseInt(getVal(sheet, dataRow, 3), 10) || 0;
            total = parseInt(getVal(sheet, dataRow, 75), 10) || 0;

            const commonDist = [];
            const lgotaDist = [];
            const targetDist = [];

            // 1. Считываем общий конкурс (суммируем данные из строки специальности и строки "Подано заявлений", защищая систему от человеческого фактора)
            for (let col = 4, score = 10.0; col <= 74; col++, score = +(score - 0.1).toFixed(1)) {
              let count = (parseInt(getVal(sheet, dataRow, col), 10) || 0) + (parseInt(getVal(sheet, dataRow + 1, col), 10) || 0);
              if (count > 0) commonDist.push({ score: +score.toFixed(1), count });
            }

            // 2. Считываем льготников вне конкурса (строка специальности + 2)
            for (let col = 4, score = 10.0; col <= 74; col++, score = +(score - 0.1).toFixed(1)) {
              let count = parseInt(getVal(sheet, dataRow + 2, col), 10) || 0;
              if (count > 0) lgotaDist.push({ score: +score.toFixed(1), count });
            }

            // 3. Считываем целевое обучение (строка специальности + 3)
            for (let col = 4, score = 10.0; col <= 74; col++, score = +(score - 0.1).toFixed(1)) {
              let count = parseInt(getVal(sheet, dataRow + 3, col), 10) || 0;
              if (count > 0) targetDist.push({ score: +score.toFixed(1), count });
            }

            // Структурированный JSON для ССО (вычисляем целевых суммированием для защиты от пустых колонок)
            distribution = {
              common: commonDist,
              lgota: lgotaDist,
              target: targetDist,
              planTarget: planTarget,
              targetTotal: targetDist.reduce((sum, item) => sum + item.count, 0)
            };
          }
        }

        const existing = await strapi.db.query('api::specialty.specialty').findOne({
          where: {
            name: config.name,
            education_level: config.level,
            form_of_study: config.form,
            category: config.category
          }
        });

        const dataPayload = {
          name: config.name,
          education_level: config.level,
          form_of_study: config.form,
          category: config.category,
          plan: plan,
          total_applications: total,
          applications_distribution: distribution, // Сохраняем структурированный объект
          publishedAt: new Date()
        };

        if (existing) {
          await strapi.entityService.update('api::specialty.specialty', existing.id, { data: dataPayload });
        } else {
          await strapi.entityService.create('api::specialty.specialty', { data: dataPayload });
        }

        updatedCount++;
      }

      // Вызов проверки позиций и отправки Email оповещений после завершения парсинга
      try {
        await checkUserAlerts();
      } catch (alertError) {
        strapi.log.error("Ошибка при проверке тревожных уведомлений: " + alertError.message);
      }

      if (ctx) {
        ctx.body = {
          success: true,
          message: `Успешно обработано специальностей: ${updatedCount}`,
          timestamp: new Date()
        };
      }

    } catch (error) {
      strapi.log.error(error);
      if (ctx && typeof ctx.badRequest === 'function') {
        ctx.badRequest("Ошибка во время парсинга таблицы: " + error.message);
      }
    }
  }
}));

/**
 * Функция сверки зарегистрированных пользователей с общей базой данных конкурса
 */
async function checkUserAlerts() {
  strapi.log.info('[Уведомления] Запуск проверки позиций абитуриентов...');

  // Извлекаем только тех пользователей, у которых заполнена анкета при регистрации
  const users = await strapi.db.query('plugin::users-permissions.user').findMany({
    where: {
      submitted_specialty: { $null: false },
      score: { $null: false }
    }
  });

  for (const user of users) {
    const userScore = parseFloat(user.score);
    if (isNaN(userScore)) continue;

    // Очищаем название специальности от скобок
    const cleanSpecName = user.submitted_specialty.replace(/\s*\(.*?\)\s*/g, '').trim();

    let formOfStudy = 'dnev';
    if (user.submitted_specialty.includes('Заочное') || user.submitted_specialty.includes('заоч')) {
      formOfStudy = 'zaoch';
    }

    // Ищем соответствующую бюджетную специальность, содержащую полный список баллов из Excel
    const specialty = await strapi.db.query('api::specialty.specialty').findOne({
      where: {
        name: cleanSpecName,
        education_level: user.education_level,
        form_of_study: formOfStudy,
        category: 'budget'
      }
    });

    if (!specialty || !specialty.plan) continue;

    const plan = specialty.plan;
    let dist = specialty.applications_distribution;
    if (typeof dist === 'string') {
      try {
        dist = JSON.parse(dist);
      } catch (e) {
        dist = {};
      }
    }

    // Получаем массив баллов всех (зарегистрированных и незарегистрированных) абитуриентов из Google Таблицы
    const commonList = dist.common || dist || [];
    let position = 1;

    // Сравниваем балл пользователя со всей базой конкурса
    if (user.education_level.startsWith('vo')) {
      let countAhead = 0;
      commonList.forEach(app => {
        const minScore = app.score - 4;
        if (userScore < minScore) {
          countAhead += app.count;
        } else if (userScore >= minScore && userScore <= app.score) {
          countAhead += app.count;
        }
      });
      position = countAhead + 1;
    } else {
      let allScores = [];
      commonList.forEach(item => {
        const countVal = parseInt(item.count, 10) || 0;
        const scoreVal = parseFloat(item.score);
        for (let i = 0; i < countVal; i++) {
          allScores.push(scoreVal);
        }
      });
      allScores.sort((a, b) => b - a);
      position = allScores.filter(s => s >= userScore).length + 1;
    }

    const isDroppedOut = position > plan;

    if (isDroppedOut) {
      if (!user.alert_sent) {
        try {
          await strapi.plugins['email'].services.email.send({
            to: user.email,
            subject: '⚠️ Внимание: Изменение вашей позиции в конкурсе БГАС',
            html: `
              <div style="font-family: Arial, sans-serif; padding: 25px; color: #2D3748; line-height: 1.6; max-width: 600px; margin: 0 auto; border: 1px solid #E2E8F0; border-radius: 12px;">
                <h2 style="color: #E53E3E; margin-top: 0; font-size: 20px;">Внимание, абитуриент!</h2>
                <p>Сообщаем вам, что в результате последнего обновления конкурсной таблицы ваша позиция по специальности <strong>${user.submitted_specialty}</strong> изменилась.</p>
                
                <div style="background-color: #FFF5F5; border-left: 4px solid #E53E3E; padding: 15px 20px; border-radius: 6px; margin: 20px 0;">
                  Вы сейчас занимаете <strong>${position}-е место</strong> в общем списке поданных заявлений при плане приема на бюджет <strong>${plan} мест</strong>.
                </div>

                <p>Вы вышли за пределы текущего проходного балла. Для сохранения шансов на поступление в академию рекомендуем войти в ваш <strong>Личный кабинет</strong> и открыть вкладку рекомендаций («Горячие окна») для выбора смежных направлений со свободными бюджетными местами.</p>
                
                <div style="text-align: center; margin-top: 25px;">
                  <a href="https://your-domain.by/index.html" style="background-color: #3182CE; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">Открыть Личный кабинет</a>
                </div>
                
                <hr style="border: none; border-top: 1px solid #E2E8F0; margin-top: 30px;">
                <small style="color: #718096; display: block; text-align: center;">Данное письмо сгенерировано автоматически системой мониторинга приемной комиссии БГАС.</small>
              </div>
            `
          });

          await strapi.db.query('plugin::users-permissions.user').update({
            where: { id: user.id },
            data: { alert_sent: true }
          });
          strapi.log.info(`[Уведомления] Предупреждение о вылете отправлено на ${user.email}`);
        } catch (err) {
          strapi.log.error(`[Уведомления] Ошибка при отправке на ${user.email}: ${err.message}`);
        }
      }
    } else {
      if (user.alert_sent) {
        await strapi.db.query('plugin::users-permissions.user').update({
          where: { id: user.id },
          data: { alert_sent: false }
        });
        strapi.log.info(`[Уведомления] Абитуриент ${user.email} вернулся в проходной список.`);
      }
    }
  }
}
