module.exports = {
  routes: [
    {
      method: 'POST',
      path: '/auth/otp-request',
      handler: 'otp-auth.requestOtp',
      config: {
        policies: [],
        auth: false,
      },
    },
    {
      method: 'POST',
      path: '/auth/otp-verify',
      handler: 'otp-auth.verifyOtp',
      config: {
        policies: [],
        auth: false,
      },
    },
    {
      method: 'POST',
      path: '/auth/recommendations', // Новый маршрут для умных подсказок (Пункт 8)
      handler: 'otp-auth.getRecommendations',
      config: {
        policies: [],
        auth: false,
      },
    },
  ],
};
