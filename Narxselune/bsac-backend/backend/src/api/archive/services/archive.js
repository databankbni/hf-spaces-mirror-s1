'use strict';

/**
 * archive service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::archive.archive');
