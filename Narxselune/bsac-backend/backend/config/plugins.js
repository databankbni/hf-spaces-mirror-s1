module.exports = ({ env }) => ({
  email: {
    config: {
      provider: 'nodemailer',
      providerOptions: {
        host: 'smtp.gmail.com',
        port: 465, // ИСПРАВЛЕНИЕ: переключили на безопасный порт SSL
        secure: true, // ИСПРАВЛЕНИЕ: включили безопасное SSL соединение
        auth: {
          user: env('SMTP_USER', 'bsacabiturienthelper@gmail.com'), // Укажите ваш Gmail
          pass: env('SMTP_PASS', 'shgklvxqbvkjvrno'), // 16-значный пароль приложения без пробелов
        },
        rejectUnauthorized: false,
      },
      settings: {
        defaultFrom: env('SMTP_USER', 'bsacabiturienthelper@gmail.com'),
        defaultReplyTo: env('SMTP_USER', 'bsacabiturienthelper@gmail.com'),
      },
    },
  },
});
