module.exports = {
  routes: [
    {
      method: 'GET',
      path: '/specialties/parse',
      handler: 'specialty.parseExcel',
      config: {
        policies: [],
        auth: false,
      },
    },
  ],
};
