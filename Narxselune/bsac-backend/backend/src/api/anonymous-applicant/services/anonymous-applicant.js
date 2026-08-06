'use strict';

/**
 * anonymous-applicant service
 */

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::anonymous-applicant.anonymous-applicant');
