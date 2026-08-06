'use strict';

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::anonymous-applicant.anonymous-applicant', ({ strapi }) => ({
  // 1. ОГРАНИЧИВАЕМ МЕТОД FIND (Защита от утечки списка абитуриентов)
  async find(ctx) {
    const { filters } = ctx.query;

    // Если фильтр по анонимному ID отсутствует — жестко блокируем запрос (ошибка 400 Bad Request)
    if (!filters || !filters.anonymous_id || !filters.anonymous_id.$eq) {
      return ctx.badRequest('Полный список зарегистрировавшихся абитуриентов закрыт настройками безопасности.');
    }

    // Если точный фильтр присутствует — выполняем безопасный поиск только этой одной записи
    return await super.find(ctx);
  },

  // 2. ОГРАНИЧИВАЕМ МЕТОД UPDATE (Защита от подделки и изменения чужих данных)
  async update(ctx) {
    const { id } = ctx.params;
    const { data } = ctx.request.body;

    if (!data || !data.anonymous_id) {
      return ctx.badRequest('Ошибка авторизации: отсутствует анонимный ID.');
    }

    // Находим оригинальную запись в базе данных по её системному ID
    const existing = await strapi.entityService.findOne('api::anonymous-applicant.anonymous-applicant', id);
    if (!existing) {
      return ctx.notFound('Запись не найдена.');
    }

    // Проверяем соответствие: редактировать запись можно только если присланный ID совпадает с базой!
    if (existing.anonymous_id !== data.anonymous_id) {
      return ctx.forbidden('Доступ запрещен. Вы не можете редактировать чужие данные.');
    }

    // Если проверки пройдены — разрешаем обновление
    return await super.update(ctx);
  }
}));
