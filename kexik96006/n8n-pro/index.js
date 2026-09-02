const express = require('express');
const cors = require('cors');
const cron = require('node-cron');
const fetch = require('node-fetch');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 7860;

app.use(cors());
app.use((req, res, next) => {
  express.json()(req, res, (err) => {
    if (err) {
      return res.status(400).json({ success: false, error: 'Invalid JSON body' });
    }
    next();
  });
});

// In-Memory Storage (7 Days Log History)
let pingLogs = [];
const MAX_LOG_AGE_MS = 7 * 24 * 60 * 60 * 1000;

// 1. Ping Supabase Function
async function pingSupabase() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey =
    process.env.SUPABASE_ANON_KEY ||
    process.env.SUPABASE_PUBLISHABLE_KEY ||
    process.env.SUPABASE_SECRET_KEY;

  const timestamp = new Date().toISOString();

  if (!supabaseUrl) {
    addLog({
      service: 'Supabase',
      timestamp,
      status: 'FAILED',
      message: 'SUPABASE_URL is missing in env vars.',
    });
    return;
  }

  try {
    const cleanUrl = supabaseUrl.replace(/\/$/, '');
    let response = await fetch(`${cleanUrl}/auth/v1/health`, { method: 'GET' });

    if (!response.ok && supabaseKey) {
      response = await fetch(`${cleanUrl}/rest/v1/`, {
        method: 'GET',
        headers: {
          apikey: supabaseKey,
          Authorization: `Bearer ${supabaseKey}`,
        },
      });
    }

    const isSuccess = response.status >= 200 && response.status < 300;
    addLog({
      service: 'Supabase',
      timestamp,
      status: isSuccess ? 'SUCCESS' : 'FAILED',
      statusCode: response.status,
      message: isSuccess
        ? 'Supabase responded successfully.'
        : `Supabase returned status code ${response.status}`,
    });
  } catch (error) {
    addLog({
      service: 'Supabase',
      timestamp,
      status: 'ERROR',
      statusCode: 500,
      message: error.message,
    });
  }
}

// 2. Ping n8n Function
async function pingN8n() {
  const n8nUrl = process.env.N8N_URL || 'https://muhammad25008-n8n-pro.hf.space/';
  const timestamp = new Date().toISOString();

  try {
    const cleanUrl = n8nUrl.replace(/\/$/, '');
    // n8n health check endpoint
    const response = await fetch(`${cleanUrl}/healthz`, { method: 'GET' });

    const isSuccess = response.status >= 200 && response.status < 300;
    addLog({
      service: 'n8n',
      timestamp,
      status: isSuccess ? 'SUCCESS' : 'FAILED',
      statusCode: response.status,
      message: isSuccess
        ? 'n8n instance responded successfully.'
        : `n8n returned status code ${response.status}`,
    });
  } catch (error) {
    addLog({
      service: 'n8n',
      timestamp,
      status: 'ERROR',
      statusCode: 500,
      message: error.message,
    });
  }
}

// Master Ping Runner
async function runAllPings(targetService = 'ALL') {
  
  if (targetService === "supabase"){
    console.log(`Running ping task for: ${targetService}`);
    await pingSupabase();
  }
  else if (targetService === "n8n"){
    console.log(`Running ping task for: ${targetService}`);
    await pingN8n();
  }
  else{
    console.log('Running ping tasks for all services...');
    await Promise.all([pingSupabase(), pingN8n()]);
  }
  
}

// Memory Clean-up & Add Log Function
function addLog(newLog) {
  const now = Date.now();
  pingLogs = pingLogs.filter((log) => {
    const logTime = new Date(log.timestamp).getTime();
    return now - logTime <= MAX_LOG_AGE_MS;
  });
  pingLogs.unshift(newLog);
}

// Cron Schedule: Runs every 12 hours
cron.schedule('0 */12 * * *', () => {
  runAllPings();
});

// Immediate ping on server start
runAllPings();

// API Endpoints
app.get('/api/status', (req, res) => {
  const lastSupabase = pingLogs.find((l) => l.service === 'Supabase') || null;
  const lastN8n = pingLogs.find((l) => l.service === 'n8n') || null;

  res.json({
    status: 'ONLINE',
    service: 'Multi-Service Keep-Alive Ping Service',
    totalLogsStored: pingLogs.length,
    services: {
      supabase: {
        url: process.env.SUPABASE_URL || 'Configured',
        lastPing: lastSupabase,
      },
      n8n: {
        url: process.env.N8N_URL,
        lastPing: lastN8n,
      },
    },
    retentionPolicy: '7 Days In-Memory Storage',
  });
});

app.get('/api/logs', (req, res) => {
  res.json({
    success: true,
    count: pingLogs.length,
    data: pingLogs,
  });
});

app.post('/api/ping-now', async (req, res) => {
  const service = req.query.service || req.body?.service;
  console.log(`Query = ${req.query.service}`);
  console.log(`Body = ${req.body?.service}`);
  await runAllPings(service);
  res.json({
    success: true,
    message: 'Manual ping triggered for all services.',
    latestLogs: pingLogs.slice(0, 2),
  });
});

app.delete('/api/logs', (req, res) => {
  pingLogs = [];
  res.json({
    success: true,
    message: 'In-memory logs cleared successfully.',
  });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});