// src/api/otp-auth/controllers/otp-auth.js

module.exports = {
  // 1. Запрос 4-значного кода на Email с регистрацией данных абитуриента (Пункт 10)
  async requestOtp(ctx) {
    const { email, education_level, education_base, score, submitted_specialty } = ctx.request.body;

    if (!email) {
      return ctx.badRequest('Email обязателен');
    }
    if (!education_level || !education_base || !score || !submitted_specialty) {
      return ctx.badRequest('Все регистрационные поля должны быть заполнены');
    }

    const numericScore = parseFloat(score);
    if (isNaN(numericScore)) {
      return ctx.badRequest('Некорректный формат балла');
    }

    const otp = Math.floor(1000 + Math.random() * 9000).toString();
    const expires = new Date(Date.now() + 10 * 60 * 1000); // 10 минут

    console.log(`\n==========================================`);
    console.log(`🔑 СГЕНЕРИРОВАН OTP КОД ДЛЯ: ${email}`);
    console.log(`👉 КОД ПОДТВЕРЖДЕНИЯ: ${otp}`);
    console.log(`==========================================\n`);

    try {
      let user = await strapi.db.query('plugin::users-permissions.user').findOne({
        where: { email: email.toLowerCase() }
      });

      if (!user) {
        user = await strapi.plugins['users-permissions'].services.user.add({
          username: email.split('@')[0] + '_' + Math.floor(Math.random() * 1000),
          email: email.toLowerCase(),
          password: Math.random().toString(36),
          confirmed: true,
          provider: 'local',
          role: 1, // Authenticated
          education_level,
          education_base,
          score: numericScore,
          submitted_specialty,
          alert_sent: false
        });
      } else {
        await strapi.db.query('plugin::users-permissions.user').update({
          where: { id: user.id },
          data: {
            education_level,
            education_base,
            score: numericScore,
            submitted_specialty
          }
        });
      }

      await strapi.db.query('plugin::users-permissions.user').update({
        where: { id: user.id },
        data: { otp_code: otp, otp_expires: expires }
      });

      strapi.plugins['email'].services.email.send({
        to: email.toLowerCase(),
        subject: 'Код подтверждения регистрации БГАС',
        html: `<div style="font-family: sans-serif; padding: 20px; color: #333;">
                 <h3>Здравствуйте!</h3>
                 <p>Вы начали процесс регистрации в Личном кабинете абитуриента БГАС.</p>
                 <p>Ваш временный 4-значный код подтверждения входа:</p>
                 <h1 style="color: #007bff; letter-spacing: 5px; font-size: 32px; margin: 20px 0;">${otp}</h1>
                 <p>Код действителен в течение 10 минут.</p>
                 <hr style="border: none; border-top: 1px solid #eee; margin-top: 20px;">
                 <small style="color: #777;">Если вы не запрашивали данный код, проигнорируйте это письмо.</small>
               </div>`
      }).then(() => {
        console.log(`✉️ Письмо с кодом успешно отправлено на адрес: ${email}`);
      }).catch(emailError => {
        console.error("❌ Ошибка отправки почты через SMTP сервер:", emailError.message);
        console.warn("⚠️ Код для входа (вывод в консоли):", otp);
      });

      return ctx.send({ ok: true, message: 'Код успешно отправлен на вашу почту' });
    } catch (err) {
      strapi.log.error(err);
      return ctx.badRequest('Ошибка генерации OTP кода');
    }
  },

  // 2. Проверка кода и выдача JWT-токена (Пункт 10)
  async verifyOtp(ctx) {
    const { email, code } = ctx.request.body;
    if (!email || !code) {
      return ctx.badRequest('Заполните все поля');
    }

    try {
      const user = await strapi.db.query('plugin::users-permissions.user').findOne({
        where: { email: email.toLowerCase() }
      });

      if (!user || user.otp_code !== code) {
        return ctx.badRequest('Неверный или устаревший код подтверждения');
      }

      const now = new Date();
      if (new Date(user.otp_expires) < now) {
        return ctx.badRequest('Срок действия кода истек, запросите новый');
      }

      await strapi.db.query('plugin::users-permissions.user').update({
        where: { id: user.id },
        data: { otp_code: null, otp_expires: null }
      });

      const jwt = strapi.plugins['users-permissions'].services.jwt.issue({ id: user.id });

      return ctx.send({
        jwt,
        user: {
          id: user.id,
          username: user.username,
          email: user.email,
          education_level: user.education_level,
          education_base: user.education_base,
          score: user.score,
          submitted_specialty: user.submitted_specialty
        }
      });
    } catch (err) {
      strapi.log.error(err);
      return ctx.badRequest('Ошибка верификации кода');
    }
  },

  // 3. Алгоритм Умных подсказок «Горячие окна» (Пункт 8)
  async getRecommendations(ctx) {
    const { score, education_level, submitted_specialty } = ctx.request.body;

    if (!education_level || !submitted_specialty || score === undefined || score === null) {
      return ctx.badRequest('Недостаточно данных для генерации рекомендаций');
    }

    const userScore = parseFloat(score);
    if (isNaN(userScore)) {
      return ctx.badRequest('Некорректный формат балла');
    }

    // Очищаем название специальности от скобок
    const cleanSubmitted = submitted_specialty.replace(/\s*\(.*?\)\s*/g, '').trim();

    let formOfStudy = 'dnev';
    if (submitted_specialty.includes('Заочное') || submitted_specialty.includes('заоч')) {
      formOfStudy = 'zaoch';
    }

    // Ищем текущую специальность пользователя
    const currentSpec = await strapi.db.query('api::specialty.specialty').findOne({
      where: {
        name: cleanSubmitted,
        education_level: education_level,
        form_of_study: formOfStudy,
        category: 'budget'
      }
    });

    if (!currentSpec) {
      return ctx.send({ showBanner: false, recommendations: [] });
    }

    const currentPlan = currentSpec.plan || 0;
    const currentDist = currentSpec.applications_distribution?.common || currentSpec.applications_distribution || [];

    let currentAllScores = [];
    currentDist.forEach(app => {
      const countVal = parseInt(app.count, 10) || 0;
      const scoreVal = parseFloat(app.score);
      for (let i = 0; i < countVal; i++) {
        currentAllScores.push(scoreVal);
      }
    });
    currentAllScores.sort((a, b) => b - a);

    let currentPosition = 1;
    if (education_level.startsWith('vo')) {
      let countAhead = 0;
      currentDist.forEach(app => {
        const minScore = app.score - 4;
        if (userScore < minScore) countAhead += app.count;
        else if (userScore >= minScore && userScore <= app.score) countAhead += app.count;
      });
      currentPosition = countAhead + 1;
    } else {
      const countAhead = currentAllScores.filter(s => s >= userScore).length;
      currentPosition = countAhead + 1;
    }

    // Условие риска вылета (риск непроизводства): позиция больше плана или составляет 90% от плана
    const isAtRisk = currentPlan > 0 && (currentPosition > currentPlan || currentPosition >= currentPlan * 0.9);

    if (!isAtRisk) {
      return ctx.send({ showBanner: false, recommendations: [] });
    }

    // Ищем абсолютно все альтернативные бюджетные специальности этого же уровня и формы обучения
    const candidates = await strapi.db.query('api::specialty.specialty').findMany({
      where: {
        name: { $ne: cleanSubmitted }, // исключаем ту специальность, на которую пользователь уже подал документы
        education_level,
        form_of_study: formOfStudy,
        category: 'budget'
      }
    });

    const recommendations = [];

    for (const cand of candidates) {
      const candPlan = cand.plan || 0;
      if (candPlan === 0) continue;

      const candDist = cand.applications_distribution?.common || cand.applications_distribution || [];
      let candAllScores = [];
      candDist.forEach(app => {
        const countVal = parseInt(app.count, 10) || 0;
        const scoreVal = parseFloat(app.score);
        for (let i = 0; i < countVal; i++) {
          candAllScores.push(scoreVal);
        }
      });
      candAllScores.sort((a, b) => b - a);

      let candPosition = 1;
      if (education_level.startsWith('vo')) {
        let countAhead = 0;
        candDist.forEach(app => {
          const minScore = app.score - 4;
          if (userScore < minScore) countAhead += app.count;
          else if (userScore >= minScore && userScore <= app.score) countAhead += app.count;
        });
        candPosition = countAhead + 1;
      } else {
        const countAhead = candAllScores.filter(s => s >= userScore).length;
        candPosition = countAhead + 1;
      }

      const totalApps = cand.total_applications || 0;
      const hasFreeSeats = totalApps < candPlan;
      const isPassing = candPosition <= candPlan;

      if (hasFreeSeats || isPassing) {
        // Вычисляем ссылку на страницу мониторинга
        let url = "";
        if (education_level === 'sso9') {
          url = cand.name.includes("веб-ресурсов") ? "../monitoring/mon_sso_9_spec1.html" :
            cand.name.includes("телекоммуникаций") ? "../monitoring/mon_sso_9_spec2.html" :
              cand.name.includes("кабельные") ? "../monitoring/mon_sso_9_spec3.html" :
                cand.name.includes("радиосвязи") ? "../monitoring/mon_sso_9_spec4.html" :
                  cand.name.includes("мультимедийных") ? "../monitoring/mon_sso_9_spec5.html" :
                    cand.name.includes("Почтовая") ? "../monitoring/mon_sso_9_spec6.html" :
                      "../monitoring/mon_sso_9_spec7.html";
        } else if (education_level === 'sso11') {
          if (formOfStudy === 'zaoch') {
            url = cand.name.includes("телекоммуникаций") ? "../monitoring/mon_sso_11_zaoch_spec5.html" :
              cand.name.includes("радиосвязи") ? "../monitoring/mon_sso_11_zaoch_spec6.html" :
                "../monitoring/mon_sso_11_zaoch_spec7.html";
          } else {
            url = cand.name.includes("телекоммуникаций") ? "../monitoring/mon_sso_11_dnev_spec1.html" :
              cand.name.includes("радиосвязи") ? "../monitoring/mon_sso_11_dnev_spec2.html" :
                cand.name.includes("Почтовая") ? "../monitoring/mon_sso_11_dnev_spec3.html" :
                  "../monitoring/mon_sso_11_dnev_spec4.html";
          }
        } else if (education_level === 'vo11') {
          url = cand.name.includes("Автоматизация") ? "../monitoring/mon_vo_11_spec1.html" :
            cand.name.includes("Системы") ? "../monitoring/mon_vo_11_spec2.html" :
              cand.name.includes("Прикладная") ? "../monitoring/mon_vo_11_spec3.html" :
                cand.name.includes("Цифровые") ? "../monitoring/mon_vo_11_spec4.html" :
                  "../monitoring/mon_vo_11_spec5.html";
        } else if (education_level === 'vosso') {
          if (formOfStudy === 'zaoch') {
            url = cand.name.includes("Системы") ? "../monitoring/mon_vo_sso_zaoch_spec4.html" :
              cand.name.includes("Прикладная") ? "../monitoring/mon_vo_sso_zaoch_spec5.html" :
                "../monitoring/mon_vo_sso_zaoch_spec6.html";
          } else {
            url = cand.name.includes("Системы") ? "../monitoring/mon_vo_sso_dnev_spec1.html" :
              cand.name.includes("Прикладная") ? "../monitoring/mon_vo_sso_dnev_spec2.html" :
                "../monitoring/mon_vo_sso_dnev_spec3.html";
          }
        }

        recommendations.push({
          name: cand.name,
          url,
          plan: candPlan,
          total: totalApps,
          position: candPosition,
          hasFreeSeats
        });
      }
    }

    // Сортировка: сначала направления со свободными местами, затем по лучшим шансам зачисления
    recommendations.sort((a, b) => {
      if (a.hasFreeSeats && !b.hasFreeSeats) return -1;
      if (!a.hasFreeSeats && b.hasFreeSeats) return 1;
      return (a.position / a.plan) - (b.position / b.plan);
    });

    return ctx.send({
      showBanner: recommendations.length > 0,
      recommendations
    });
  }
};
