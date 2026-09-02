# -*- coding: utf-8 -*-
"""
CustomerCore Operations Console — Single Page Application Frontend (ui.py)
A premium dashboard for testing and visualizing the AI triage pipeline.
"""

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CustomerCore Operations Console</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0a0e17;
            --bg-card: rgba(18, 26, 47, 0.6);
            --bg-card-border: rgba(255, 255, 255, 0.08);
            --primary: #6366f1;
            --primary-glow: rgba(99, 102, 241, 0.4);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.3);
            --warning: #f59e0b;
            --danger: #ef4444;
            --danger-glow: rgba(239, 68, 68, 0.3);
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --text-glow: rgba(255, 255, 255, 0.15);
            --glass-backdrop: blur(16px);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.12) 0%, transparent 40%);
            background-attachment: fixed;
        }

        /* Layout */
        .sidebar {
            width: 280px;
            background: rgba(10, 14, 23, 0.85);
            border-right: 1px solid var(--bg-card-border);
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
            backdrop-filter: var(--glass-backdrop);
            z-index: 10;
        }

        .main-content {
            flex: 1;
            padding: 40px;
            overflow-y: auto;
            max-width: 1440px;
            margin: 0 auto;
            width: 100%;
        }

        /* Sidebar Logo & Header */
        .logo-container {
            display: flex;
            align-items: center;
            gap: 12px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--bg-card-border);
        }

        .logo-icon {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, var(--primary), var(--success));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            color: white;
            font-size: 18px;
            box-shadow: 0 0 15px var(--primary-glow);
        }

        .logo-text h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: linear-gradient(to right, #ffffff, #a5b4fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-text span {
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            display: block;
        }

        /* Sidebar Navigation */
        .nav-menu {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 14px 16px;
            border-radius: 12px;
            color: var(--text-muted);
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid transparent;
            cursor: pointer;
        }

        .nav-item:hover {
            color: white;
            background: rgba(255, 255, 255, 0.03);
            border-color: rgba(255, 255, 255, 0.05);
        }

        .nav-item.active {
            color: white;
            background: rgba(99, 102, 241, 0.15);
            border-color: rgba(99, 102, 241, 0.25);
            box-shadow: inset 0 0 12px rgba(99, 102, 241, 0.05);
        }

        .nav-icon {
            font-size: 18px;
        }

        /* Header Intro Card (HR / Recruiter Friendly) */
        .info-banner {
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(16, 185, 129, 0.06));
            border: 1px solid rgba(99, 102, 241, 0.25);
            border-radius: 16px;
            padding: 20px 24px;
            margin-bottom: 30px;
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .info-badge {
            background: var(--primary);
            color: white;
            font-size: 28px;
            width: 56px;
            height: 56px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            box-shadow: 0 0 15px var(--primary-glow);
        }

        .info-text h3 {
            font-family: 'Outfit', sans-serif;
            font-size: 16px;
            font-weight: 600;
            color: white;
            margin-bottom: 4px;
        }

        .info-text p {
            font-size: 13.5px;
            color: #d1d5db;
            line-height: 1.5;
        }

        /* Session / Token Control Panel (Top Right Layout) */
        .top-session-bar {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 16px;
            padding: 16px 24px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }

        .session-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .session-status {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background-color: var(--success);
            box-shadow: 0 0 10px var(--success-glow);
            display: inline-block;
        }

        .session-title {
            font-size: 13px;
            font-weight: 600;
            color: white;
        }

        .session-controls {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .control-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .control-item label {
            font-size: 12px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .control-item select {
            width: auto;
            min-width: 140px;
            max-width: 260px;
            padding: 8px 28px 8px 12px;
            background: rgba(10, 14, 23, 0.9);
            border: 1px solid var(--bg-card-border);
            border-radius: 8px;
            font-size: 12px;
            color: var(--text-main);
            appearance: none;
            -webkit-appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%239ca3af'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 10px center;
            cursor: pointer;
            transition: border-color 0.2s ease;
        }

        .control-item select:hover {
            border-color: rgba(99, 102, 241, 0.4);
        }

        .control-item select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
        }

        .auth-status {
            font-size: 11px;
            font-weight: 600;
            padding: 6px 14px;
            border-radius: 20px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s ease;
        }
        .auth-ok {
            background: rgba(16, 185, 129, 0.12);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.25);
        }
        .auth-fail {
            background: rgba(239, 68, 68, 0.12);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.25);
        }

        /* Demo Cases / Presets */
        .demo-presets {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .preset-btn {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--bg-card-border);
            color: #d1d5db;
            padding: 8px 14px;
            border-radius: 30px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
        }

        .preset-btn:hover {
            background: rgba(99, 102, 241, 0.1);
            border-color: var(--primary);
            color: white;
        }

        /* Form & Result Grid */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 460px 1fr;
            gap: 32px;
            align-items: start;
        }

        .glass-card {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 20px;
            padding: 28px;
            backdrop-filter: var(--glass-backdrop);
        }

        .form-group {
            margin-bottom: 18px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        select, input, textarea {
            background: rgba(10, 14, 23, 0.8);
            border: 1px solid var(--bg-card-border);
            color: white;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 13px;
            width: 100%;
            outline: none;
            transition: border-color 0.3s;
        }

        select:focus, input:focus, textarea:focus {
            border-color: var(--primary);
        }

        .btn {
            background: linear-gradient(135deg, var(--primary), #4f46e5);
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .btn:hover {
            box-shadow: 0 0 15px var(--primary-glow);
            transform: translateY(-1px);
        }

        .btn-success {
            background: linear-gradient(135deg, var(--success), #059669);
        }

        .btn-success:hover {
            box-shadow: 0 0 15px var(--success-glow);
        }

        /* Dashboard View Elements */
        .tab-view {
            display: none;
            animation: fadeIn 0.4s ease-out;
        }

        .tab-view.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .view-header {
            margin-bottom: 24px;
        }

        .view-header h2 {
            font-family: 'Outfit', sans-serif;
            font-size: 28px;
            font-weight: 700;
            color: white;
            margin-bottom: 6px;
        }

        .view-header p {
            color: var(--text-muted);
            font-size: 14px;
        }

        /* Analytics Output Panel */
        .analytics-panel {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        .analytics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
            gap: 20px;
        }

        .metric-card {
            background: rgba(18, 26, 47, 0.4);
            border: 1px solid var(--bg-card-border);
            border-radius: 16px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            transition: all 0.3s;
        }

        .metric-card:hover {
            border-color: rgba(255, 255, 255, 0.12);
            transform: translateY(-2px);
        }

        .metric-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .metric-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            font-weight: 600;
        }

        .metric-icon {
            font-size: 18px;
        }

        .metric-value {
            font-family: 'Outfit', sans-serif;
            font-size: 20px;
            font-weight: 700;
        }

        /* Priority Colors */
        .priority-badge {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            display: inline-block;
        }
        .priority-critical { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.25); }
        .priority-high { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.25); }
        .priority-medium { background: rgba(99, 102, 241, 0.15); color: var(--primary); border: 1px solid rgba(99, 102, 241, 0.25); }
        .priority-low { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.25); }

        /* Progress Bar for Churn */
        .churn-container {
            width: 100%;
            height: 8px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 4px;
            overflow: hidden;
            margin-top: 6px;
        }

        .churn-bar {
            height: 100%;
            width: 0%;
            border-radius: 4px;
            background: linear-gradient(to right, var(--success), var(--warning), var(--danger));
            transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        }

        /* Large Output Areas (Resolution / PII) */
        .large-metric-card {
            background: rgba(18, 26, 47, 0.4);
            border: 1px solid var(--bg-card-border);
            border-radius: 16px;
            padding: 24px;
        }

        .log-box {
            background: rgba(10, 14, 23, 0.9);
            border: 1px solid var(--bg-card-border);
            padding: 16px;
            border-radius: 10px;
            font-family: monospace;
            font-size: 13px;
            line-height: 1.5;
            color: #d1d5db;
            overflow-x: auto;
            max-height: 250px;
            overflow-y: auto;
        }

        /* Safety Banner */
        .safety-banner {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 18px 24px;
            border-radius: 16px;
            margin-bottom: 8px;
            font-weight: 500;
        }
        .safety-passed {
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.2);
            color: var(--success);
        }
        .safety-blocked {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: var(--danger);
            animation: pulse-border 2s infinite;
        }
        @keyframes pulse-border {
            0% { border-color: rgba(239, 68, 68, 0.2); }
            50% { border-color: rgba(239, 68, 68, 0.6); }
            100% { border-color: rgba(239, 68, 68, 0.2); }
        }

        /* Tables */
        .table-container {
            width: 100%;
            overflow-x: auto;
            margin-top: 24px;
            border-radius: 16px;
            border: 1px solid var(--bg-card-border);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13px;
        }

        th {
            background: rgba(10, 14, 23, 0.6);
            color: var(--text-muted);
            font-weight: 600;
            padding: 14px 18px;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.8px;
            border-bottom: 1px solid var(--bg-card-border);
        }

        td {
            padding: 14px 18px;
            border-bottom: 1px solid var(--bg-card-border);
            color: #d1d5db;
        }

        tr:hover td {
            background: rgba(255, 255, 255, 0.01);
            color: white;
        }

        .empty-state {
            padding: 40px;
            text-align: center;
            color: var(--text-muted);
            font-size: 14px;
        }

        /* Health statuses badges */
        .health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }

        .status-badge {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .status-badge.ok { background: rgba(16, 185, 129, 0.15); color: var(--success); }
        .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
        .status-badge.info { background: rgba(99, 102, 241, 0.15); color: var(--primary); }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            background-color: currentColor;
            animation: pulse-dot 1.5s infinite;
        }

        @keyframes pulse-dot {
            0% { transform: scale(0.9); opacity: 0.6; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.9); opacity: 0.6; }
        }

        /* Toast notifications */
        .toast {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: rgba(10, 14, 23, 0.95);
            border: 1px solid var(--bg-card-border);
            padding: 16px 24px;
            border-radius: 12px;
            color: white;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            z-index: 100;
            display: flex;
            align-items: center;
            gap: 12px;
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            font-size: 13px;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }
    </style>
</head>
<body>

    <!-- Sidebar Layout -->
    <div class="sidebar">
        <div class="logo-container">
            <div class="logo-icon">C</div>
            <div class="logo-text">
                <h1>CustomerCore</h1>
                <span>Operations Console</span>
            </div>
        </div>

        <div class="nav-menu">
            <div class="nav-item active" onclick="switchTab('dashboard-view')">
                <span class="nav-icon">📊</span> Triage Dashboard
            </div>
            <div class="nav-item" onclick="switchTab('hitl-view')">
                <span class="nav-icon">🤝</span> HITL Workspace
            </div>
            <div class="nav-item" onclick="switchTab('health-view')">
                <span class="nav-icon">⚡</span> System Health
            </div>
        </div>

        <div style="margin-top: auto; font-size: 11px; color: var(--text-muted); border-top: 1px solid var(--bg-card-border); padding-top: 16px; text-align: center;">
            Version 1.0.0 (FastAPI Core)<br>
            <a href="/docs" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Swagger API Docs ↗</a>
        </div>
    </div>

    <!-- Main View Section -->
    <div class="main-content">

        <!-- TOAST -->
        <div id="toast-notify" class="toast">
            <span id="toast-icon">ℹ️</span>
            <span id="toast-message">Notification message</span>
        </div>

        <!-- HR / RECRUITER EXPLANATION BANNER -->
        <div class="info-banner">
            <div class="info-badge">🚀</div>
            <div class="info-text">
                <h3>B2B AI Customer Intelligence Platform & Triage Engine</h3>
                <p>
                    CustomerCore uses a stateful <strong>LangGraph supervisor network</strong> of 6 specialized AI agents to process customer support tickets. 
                    The pipeline classifies urgency, routes to departments, masks sensitive PII (EU AI Act privacy compliance), predicts churn risk, detects systemic outage anomalies, and automatically generates resolution responses.
                </p>
            </div>
        </div>

        <!-- SESSION / AUTHENTICATION CONTROL BAR -->
        <div class="top-session-bar">
            <div class="session-info">
                <span class="session-status" id="session-dot"></span>
                <span class="session-title">Active Session Context</span>
            </div>
            <div class="session-controls">
                <div class="control-item">
                    <label>Tenant</label>
                    <select id="widget-tenant" onchange="generateToken()">
                        <option value="acme-corp" selected>Acme Corp (Tenant A)</option>
                        <option value="globex">Globex Inc (Tenant B)</option>
                        <option value="hooli">Hooli Ltd (Tenant C)</option>
                        <option value="test-tenant">Test Tenant</option>
                    </select>
                </div>
                <div class="control-item">
                    <label>Role</label>
                    <select id="widget-role" onchange="generateToken()">
                        <option value="support_agent">Support Agent</option>
                        <option value="manager" selected>Manager (HITL Access)</option>
                        <option value="admin">Administrator</option>
                    </select>
                </div>
                <span class="auth-status auth-ok" id="auth-status">
                    <span style="width: 7px; height: 7px; border-radius: 50%; background-color: currentColor; display: inline-block; animation: pulse-dot 1.5s infinite;"></span>
                    <span id="auth-status-text">Authenticated</span>
                </span>
            </div>
        </div>

        <!-- TAB 1: TRIAGE DASHBOARD -->
        <div id="dashboard-view" class="tab-view active">
            <div class="view-header">
                <h2>AI Triage Pipeline</h2>
                <p>Test the end-to-end streaming classification and guardrail compliance pipeline</p>
            </div>

            <!-- Demo Presets (1-Click case loaders) -->
            <div style="margin-bottom: 12px; font-size: 12px; color: var(--text-muted); font-weight: 600;">1-CLICK DEMO CASES (QUICK TESTS):</div>
            <div class="demo-presets">
                <button class="preset-btn" onclick="loadPreset('billing')">💳 Billing Escalation (High Churn Risk)</button>
                <button class="preset-btn" onclick="loadPreset('outage')">🚨 Server Outage Anomaly (Critical Priority)</button>
                <button class="preset-btn" onclick="loadPreset('privacy')">🔒 PII Leak / Safety Violation (Blocked & HITL Gated)</button>
            </div>

            <div class="dashboard-grid">
                <!-- Left column: Submit Ticket Form -->
                <div class="glass-card">
                    <h3 style="margin-bottom: 20px; font-size: 18px; font-family: 'Outfit';">Submit Support Ticket</h3>
                    <form id="triage-form" onsubmit="submitTriage(event)">
                        <div class="form-group">
                            <label>Customer ID</label>
                            <input type="text" id="cust-id" value="cust_billing_01" required>
                        </div>
                        <div class="form-group">
                            <label>Customer Tier</label>
                            <select id="cust-tier">
                                <option value="free">Free Tier</option>
                                <option value="starter">Starter Tier</option>
                                <option value="growth">Growth Tier</option>
                                <option value="enterprise" selected>Enterprise Tier</option>
                                <option value="vip">VIP Tier</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Source / Channel</label>
                            <select id="ticket-channel">
                                <option value="email" selected>Email</option>
                                <option value="console">Operations Console</option>
                                <option value="api">API Gateway</option>
                                <option value="slack">Slack</option>
                                <option value="webhook">Webhook</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Support Ticket Text</label>
                            <textarea id="ticket-text" rows="7" required>Write the support issue here...</textarea>
                        </div>
                        <button type="submit" class="btn" style="width: 100%;" id="submit-btn">
                            🚀 Dispatch to Triage Pipeline
                        </button>
                    </form>
                </div>

                <!-- Right column: Analytics Display -->
                <div class="analytics-panel">
                    <!-- Safety compliance banner -->
                    <div id="safety-indicator" class="safety-banner safety-passed" style="display: none;">
                        <span id="safety-icon">🛡️</span>
                        <span id="safety-text">AI Compliance Check: Safe</span>
                    </div>

                    <div class="analytics-grid">
                        <!-- Priority Card -->
                        <div class="metric-card">
                            <div class="metric-header">
                                <span class="metric-label">Predicted Priority</span>
                                <span class="metric-icon">🔥</span>
                            </div>
                            <div id="metric-priority" class="metric-value">--</div>
                        </div>

                        <!-- Routing Card -->
                        <div class="metric-card">
                            <div class="metric-header">
                                <span class="metric-label">Smart Routing Team</span>
                                <span class="metric-icon">🎯</span>
                            </div>
                            <div id="metric-routing" class="metric-value">--</div>
                        </div>

                        <!-- Churn Risk Card -->
                        <div class="metric-card">
                            <div class="metric-header">
                                <span class="metric-label">Predicted Churn Risk</span>
                                <span class="metric-icon">⚠️</span>
                            </div>
                            <div style="display: flex; flex-direction: column; justify-content: center; height: 100%;">
                                <div id="metric-churn" class="metric-value" style="margin-bottom: 2px;">--</div>
                                <div class="churn-container">
                                    <div id="churn-progress" class="churn-bar"></div>
                                </div>
                            </div>
                        </div>

                        <!-- Outage Check Card -->
                        <div class="metric-card">
                            <div class="metric-header">
                                <span class="metric-label">Anomaly / Outage Check</span>
                                <span class="metric-icon">🌐</span>
                            </div>
                            <div id="metric-outage" class="metric-value">--</div>
                        </div>
                    </div>

                    <!-- AI Suggested Resolution -->
                    <div class="large-metric-card">
                        <h4 style="margin-bottom: 12px; font-size: 13px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px;">
                            Suggested Agent Resolution
                        </h4>
                        <div id="metric-resolution" style="font-size: 14px; line-height: 1.6; color: #e5e7eb; min-height: 50px;">
                            Load a preset or write a ticket to see the AI agent's processed output here.
                        </div>
                    </div>

                    <!-- PII Redaction Log -->
                    <div class="large-metric-card">
                        <h4 style="margin-bottom: 12px; font-size: 13px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px;">
                            Privacy Vault (PII Masking Audit Log)
                        </h4>
                        <div class="log-box" id="metric-pii-log">
                            Audit logs will display once a ticket is evaluated.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bottom Table: History -->
            <div class="glass-card" style="margin-top: 40px; padding: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h3 style="font-family: 'Outfit'; font-size: 18px;">Tenant Ticket History</h3>
                    <button class="btn" style="padding: 8px 16px;" onclick="loadHistory()">🔄 Refresh List</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Ticket ID</th>
                                <th>Customer ID</th>
                                <th>Tier</th>
                                <th>Priority</th>
                                <th>Status</th>
                                <th>Created At</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="history-table-body">
                            <tr>
                                <td colspan="7" class="empty-state">No tickets triaged yet. Load a preset above!</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 2: HITL WORKSPACE -->
        <div id="hitl-view" class="tab-view">
            <div class="view-header">
                <h2>Human-in-the-Loop Workspace</h2>
                <p>Inspect and override tickets flagged by compliance policies (requires Manager/Admin roles)</p>
            </div>

            <div class="glass-card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
                    <h3 style="font-family: 'Outfit'; font-size: 18px;">Flagged HITL Reviews</h3>
                    <button id="btn-fetch-hitl" class="btn" style="padding: 8px 16px;" onclick="loadHITLList()">🔄 Fetch Pending</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Ticket ID</th>
                                <th>Customer ID</th>
                                <th>Content Snip</th>
                                <th>Flagged Reasons / Violations</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="hitl-table-body">
                            <tr>
                                <td colspan="5" class="empty-state">No tickets pending HITL review.</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 3: SYSTEM HEALTH -->
        <div id="health-view" class="tab-view">
            <div class="view-header">
                <h2>System Health Monitor</h2>
                <p>Check the live connection status of CustomerCore microservices</p>
            </div>

            <div class="glass-card">
                <h3 style="margin-bottom: 24px; font-family: 'Outfit'; font-size: 18px;">Microservice Connectivity</h3>
                <div class="health-grid">
                    <!-- API Status -->
                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-label">API REST Server</span>
                            <span class="metric-icon">🚀</span>
                        </div>
                        <div>
                            <span class="status-badge ok"><span class="pulse-dot"></span>Active</span>
                        </div>
                    </div>

                    <!-- Redis Status -->
                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-label">Redis Cache</span>
                            <span class="metric-icon">⚡</span>
                        </div>
                        <div>
                            <span id="health-redis" class="status-badge error">Checking...</span>
                        </div>
                    </div>

                    <!-- Redpanda Status -->
                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-label">Redpanda Broker</span>
                            <span class="metric-icon">📻</span>
                        </div>
                        <div>
                            <span id="health-redpanda" class="status-badge info">Checking...</span>
                        </div>
                    </div>

                    <!-- Supabase Status -->
                    <div class="metric-card">
                        <div class="metric-header">
                            <span class="metric-label">Supabase DB</span>
                            <span class="metric-icon">🗄️</span>
                        </div>
                        <div>
                            <span id="health-supabase" class="status-badge error">Checking...</span>
                        </div>
                    </div>
                </div>

                <div style="margin-top: 40px;">
                    <h3 style="margin-bottom: 16px; font-family: 'Outfit'; font-size: 18px;">FastAPI Configuration Settings</h3>
                    <div class="log-box" id="health-config-log">
                        Loading configuration...
                    </div>
                </div>
            </div>
        </div>

    </div>

    <!-- JS Logic -->
    <script>
        let currentToken = "";

        const presets = {
            billing: {
                tenant: "acme-corp",
                role: "manager",
                custId: "cust_billing_01",
                tier: "enterprise",
                channel: "email",
                text: "I am extremely upset with your service. Our billing billing renewal went through but our payment failed twice. The system charged my card $500 twice and the API returns 500 server errors. Please refund our money immediately and fix the account, or we will cancel our subscription by the end of today."
            },
            outage: {
                tenant: "globex",
                role: "manager",
                custId: "cust_outage_99",
                tier: "enterprise",
                channel: "api",
                text: "CRITICAL: Our production servers are completely down. The API endpoint /v1/predict is returning 502 Bad Gateway and 500 Internal Server errors to all our active clients. We have over 2,000 customers affected. This is a severe outage affecting our SLAs, please escalate this immediately to the engineering lead."
            },
            privacy: {
                tenant: "hooli",
                role: "support_agent",
                custId: "cust_privacy_02",
                tier: "growth",
                channel: "email",
                text: "Hi support, my name is Richard Hendricks. I need to update my account payment details. My credit card number is 4111 2222 3333 4444, exp 12/28, security code 123. Also my phone number is 555-0199 and my social security number is 000-12-3456. Can you promise me a full refund of $500 if I do this? Let me know right now."
            }
        };

        // Load 1-Click Preset Scenario
        function loadPreset(key) {
            const data = presets[key];
            if (!data) return;

            // Load values to controls
            document.getElementById('widget-tenant').value = data.tenant;
            document.getElementById('widget-role').value = data.role;
            
            document.getElementById('cust-id').value = data.custId;
            document.getElementById('cust-tier').value = data.tier;
            document.getElementById('ticket-channel').value = data.channel;
            document.getElementById('ticket-text').value = data.text;

            showToast(`Preset Loaded: ${key.toUpperCase()} scenario. Fetching scoped token...`);
            generateToken();
        }

        // Tab Switch
        function switchTab(tabId) {
            document.querySelectorAll('.tab-view').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            
            // Map click to nav highlight
            if(tabId === 'dashboard-view') {
                document.querySelector('.nav-menu .nav-item:nth-child(1)').classList.add('active');
                loadHistory();
            } else if(tabId === 'hitl-view') {
                document.querySelector('.nav-menu .nav-item:nth-child(2)').classList.add('active');
                loadHITLList();
            } else if(tabId === 'health-view') {
                document.querySelector('.nav-menu .nav-item:nth-child(3)').classList.add('active');
                checkSystemHealth();
            }
        }

        // Notification Toast
        function showToast(message, isError = false) {
            const toast = document.getElementById('toast-notify');
            const icon = document.getElementById('toast-icon');
            const msg = document.getElementById('toast-message');

            icon.innerText = isError ? "❌" : "✅";
            msg.innerText = message;
            
            toast.className = "toast show";
            setTimeout(() => {
                toast.className = "toast";
            }, 3000);
        }

        async function generateToken() {
            const tenantEl = document.getElementById('widget-tenant');
            const roleEl = document.getElementById('widget-role');
            const tenant = tenantEl.value;
            const role = roleEl.value;
            
            // Adjust dropdown widths automatically
            adjustSelectWidth(tenantEl);
            adjustSelectWidth(roleEl);
            
            // Immediately enforce HITL access restriction if role is not manager/admin
            if (role !== "manager" && role !== "admin") {
                const tbody = document.getElementById('hitl-table-body');
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="color: var(--danger); font-weight: 500;">Access Denied: Only Manager or Admin role can access HITL reviews.</td></tr>`;
                }
            }
            
            const authBadge = document.getElementById('auth-status');
            const authText = document.getElementById('auth-status-text');
            const sessionDot = document.getElementById('session-dot');
            
            try {
                const response = await fetch(`/api/v1/test-token?tenant_id=${tenant}&role=${role}`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                if(data.token) {
                    currentToken = data.token;
                    authBadge.className = "auth-status auth-ok";
                    authText.innerText = "Authenticated";
                    sessionDot.style.backgroundColor = "var(--success)";
                    sessionDot.style.boxShadow = "0 0 10px var(--success-glow)";
                    
                    // Reload histories
                    if(document.getElementById('dashboard-view').classList.contains('active')) {
                        loadHistory();
                    } else if(document.getElementById('hitl-view').classList.contains('active')) {
                        loadHITLList();
                    }
                } else {
                    throw new Error("No token returned by API");
                }
            } catch(e) {
                console.error("Token generation failed", e);
                authBadge.className = "auth-status auth-fail";
                authText.innerText = "Auth Failed";
                sessionDot.style.backgroundColor = "var(--danger)";
                sessionDot.style.boxShadow = "0 0 10px var(--danger-glow)";
                showToast("Session authentication failed — retrying...", true);
                // Auto-retry after 3 seconds
                setTimeout(() => generateToken(), 3000);
            }
        }

        // Submit Ticket
        async function submitTriage(event) {
            event.preventDefault();
            const text = document.getElementById('ticket-text').value;
            const custId = document.getElementById('cust-id').value;
            const custTier = document.getElementById('cust-tier').value;
            const channel = document.getElementById('ticket-channel').value;
            const btn = document.getElementById('submit-btn');

            btn.disabled = true;
            btn.innerText = "Processing...";

            // Reset UI outputs
            document.getElementById('metric-priority').innerText = "--";
            document.getElementById('metric-priority').className = "metric-value";
            document.getElementById('metric-routing').innerText = "--";
            document.getElementById('metric-outage').innerText = "--";
            document.getElementById('metric-churn').innerText = "--";
            document.getElementById('churn-progress').style.width = "0%";
            document.getElementById('metric-resolution').innerText = "Processing ticket...";
            document.getElementById('metric-pii-log').innerText = "Masking PII...";
            document.getElementById('safety-indicator').style.display = "none";

            try {
                const response = await fetch('/api/v1/triage', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${currentToken}`
                    },
                    body: JSON.stringify({
                        text: text,
                        customer_id: custId,
                        customer_tier: custTier,
                        channel: channel
                    })
                });

                if(!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const result = await response.json();
                showToast("Ticket submitted to triage pipeline!");
                pollTicketStatus(result.ticket_id);
            } catch(e) {
                console.error("Submit failed", e);
                showToast("Failed to submit ticket", true);
                btn.disabled = false;
                btn.innerText = "Dispatch to Triage Pipeline";
                document.getElementById('metric-resolution').innerText = "Failed to submit ticket. See logs.";
            }
        }

        // Poll Ticket Status
        async function pollTicketStatus(ticketId) {
            const btn = document.getElementById('submit-btn');
            let attempts = 0;
            const maxAttempts = 15;

            const pollInterval = setInterval(async () => {
                attempts++;
                try {
                    const response = await fetch(`/api/v1/triage/${ticketId}`, {
                        headers: {
                            'Authorization': `Bearer ${currentToken}`
                        }
                    });

                    if(response.status === 404) {
                        return;
                    }

                    if(!response.ok) {
                        throw new Error(`HTTP error ${response.status}`);
                    }

                    const data = await response.json();
                    
                    if (data.status === "processing") {
                        document.getElementById('metric-resolution').innerText = `Triage active: Supervisor routing & agent network running (attempt ${attempts}/15)...`;
                    }
                    
                    if(data.status !== "pending" && data.status !== "processing" || attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        if (attempts >= maxAttempts && (data.status === "pending" || data.status === "processing")) {
                            data.status = "failed";
                            data.error_message = "Triage pipeline execution timed out after 15 seconds. The supervisor did not complete in time.";
                        }
                        displayTriageResults(data);
                        btn.disabled = false;
                        btn.innerText = "Dispatch to Triage Pipeline";
                        loadHistory();
                    }
                } catch(e) {
                    console.error("Polling error", e);
                    clearInterval(pollInterval);
                    btn.disabled = false;
                    btn.innerText = "Dispatch to Triage Pipeline";
                    showToast("Triage pipeline tracking error — please check connectivity", true);
                }
            }, 1000);
        }

        // Display results in dashboard metrics cards
        function displayTriageResults(data) {
            if (data.status === "failed") {
                const priorityEl = document.getElementById('metric-priority');
                priorityEl.innerText = "FAILED";
                priorityEl.className = "metric-value priority-badge priority-critical";

                document.getElementById('metric-routing').innerText = "Aborted";
                document.getElementById('metric-outage').innerText = "Error";
                document.getElementById('metric-churn').innerText = "N/A";
                document.getElementById('churn-progress').style.width = "0%";

                const resolutionEl = document.getElementById('metric-resolution');
                resolutionEl.innerHTML = `
                    <div style="color: var(--danger); font-weight: 700; font-size: 15px; margin-bottom: 8px;">Triage Pipeline Execution Failed ❌</div>
                    <div style="font-family: monospace; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); padding: 12px; border-radius: 8px; color: #fca5a5; font-size: 12.5px; margin-bottom: 12px; overflow-x: auto; white-space: pre-wrap; line-height: 1.4;">${data.error_message || 'An unexpected exception occurred.'}</div>
                    <div style="font-size: 12px; color: var(--text-muted);">
                        <strong>Next Steps:</strong> Check system logs, verify Supabase credentials/IP reachability, and check the status of external LLM endpoints (e.g. OpenRouter key balance).
                    </div>
                `;

                document.getElementById('metric-pii-log').innerText = `[Pipeline Aborted]\n- Ticket ID: ${data.ticket_id || '--'}\n- Status: Failed\n- Error: ${data.error_message || 'unknown'}`;
                
                const safetyEl = document.getElementById('safety-indicator');
                const safetyText = document.getElementById('safety-text');
                safetyEl.className = "safety-banner safety-blocked";
                safetyText.innerText = "🛡️ AI Compliance Check: Aborted due to system error.";
                safetyEl.style.display = "flex";
                return;
            }

            // Priority
            const priorityVal = data.priority || "Low";
            const priorityEl = document.getElementById('metric-priority');
            priorityEl.innerText = priorityVal;
            priorityEl.className = `metric-value priority-badge priority-${priorityVal.toLowerCase()}`;

            // Routing
            const routingTeam = (data.escalation_team || data.category || "General Support").replace(/_/g, ' ');
            document.getElementById('metric-routing').innerText = routingTeam;

            // Outage
            document.getElementById('metric-outage').innerText = data.incident_active ? "⚠️ Outage Alert!" : "✅ Normal";

            // Churn Risk
            let churnPercent = 15;
            if (data.churn_risk === "low") churnPercent = 15;
            else if (data.churn_risk === "medium") churnPercent = 45;
            else if (data.churn_risk === "high") churnPercent = 75;
            else if (data.churn_risk === "critical") churnPercent = 95;
            else if (data.churn_risk_score !== undefined) churnPercent = Math.round(data.churn_risk_score * 100);
            
            document.getElementById('metric-churn').innerText = `${churnPercent}%`;
            document.getElementById('churn-progress').style.width = `${churnPercent}%`;

            // Suggested Resolution
            document.getElementById('metric-resolution').innerText = data.suggested_resolution || "A support representative has been notified and will contact you shortly.";

            // PII masking logs
            let piiText = `[Vault Ingestion]\n`;
            piiText += `- Ticket ID: ${data.ticket_id || '--'}\n`;
            piiText += `- Customer ID: ${data.customer_id || '--'}\n`;
            piiText += `- Raw Text masked? Yes\n`;
            if (data.masked_text || data.text) {
                piiText += `- Redacted Body: "${data.masked_text || data.text}"\n`;
            }
            document.getElementById('metric-pii-log').innerText = piiText;

            // Safety indicator
            const safetyEl = document.getElementById('safety-indicator');
            const safetyText = document.getElementById('safety-text');
            
            if (data.constitutional_blocked) {
                safetyEl.className = "safety-banner safety-blocked";
                safetyText.innerText = "🛡️ AI Compliance Check: BLOCKED! Input/Output policy violations detected.";
                
                if (data.constitutional_violations && data.constitutional_violations.length > 0) {
                    piiText += `\n[Safety Violations Detected]\n`;
                    data.constitutional_violations.forEach(v => {
                        const ruleId = v.rule || v.rule_id || "UNKNOWN_RULE";
                        const reason = v.explanation || v.reason || "Safety policy trigger";
                        piiText += `- Rule: ${ruleId} | Reason: ${reason}\n`;
                    });
                    document.getElementById('metric-pii-log').innerText = piiText;
                }
            } else {
                safetyEl.className = "safety-banner safety-passed";
                safetyText.innerText = "🛡️ AI Compliance Check: Passed! All content satisfies safety regulations.";
            }
            safetyEl.style.display = "flex";
        }

        // Load Ticket History for active tenant
        async function loadHistory() {
            const tbody = document.getElementById('history-table-body');
            
            try {
                const response = await fetch('/api/v1/triage', {
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    }
                });

                if(!response.ok) {
                    let errMsg = `HTTP error ${response.status} ${response.statusText}`;
                    try {
                        const errData = await response.json();
                        if (errData && errData.detail) {
                            errMsg += ` - ${errData.detail}`;
                        } else if (errData && errData.error) {
                            errMsg += ` - ${errData.error}`;
                        }
                    } catch(_) {}
                    throw new Error(errMsg);
                }

                const tickets = await response.json();
                if(tickets.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No tickets triaged yet. Load a preset above!</td></tr>`;
                    return;
                }

                tbody.innerHTML = "";
                tickets.forEach(t => {
                    const tr = document.createElement('tr');
                    const priorityClass = t.priority ? t.priority.toLowerCase() : 'low';
                    
                    tr.innerHTML = `
                        <td style="font-family: monospace;">${t.ticket_id.slice(0, 8)}...</td>
                        <td>${t.customer_id}</td>
                        <td><span style="text-transform: capitalize;">${t.customer_tier}</span></td>
                        <td><span class="priority-badge priority-${priorityClass}">${t.priority || 'Low'}</span></td>
                        <td><span class="status-badge info" style="padding: 2px 8px; font-size: 11px;">${t.status}</span></td>
                        <td>${new Date(t.created_at || Date.now()).toLocaleString()}</td>
                        <td>
                            <button class="btn" style="padding: 4px 8px; font-size: 11px;" onclick="loadSingleTicket('${t.ticket_id}')">👁️ View</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch(e) {
                console.error("Load history failed", e);
                tbody.innerHTML = `<tr><td colspan="7" class="empty-state" style="color: var(--danger); font-weight: 500;">Failed to load ticket history.<br><span style="font-size: 12px; font-family: monospace; color: var(--text-muted); display: block; margin-top: 8px;">${e.message}</span></td></tr>`;
            }
        }

        // View single ticket details
        async function loadSingleTicket(ticketId) {
            try {
                const response = await fetch(`/api/v1/triage/${ticketId}`, {
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    }
                });
                if(response.ok) {
                    const data = await response.json();
                    displayTriageResults(data);
                    showToast(`Loaded ticket ${ticketId.slice(0, 8)}`);
                }
            } catch(e) {
                showToast("Failed to load ticket details", true);
            }
        }

        // Load HITL Pending list
        async function loadHITLList() {
            const tbody = document.getElementById('hitl-table-body');
            const btn = document.getElementById('btn-fetch-hitl');
            
            // Strict Role-Based Access Control in the Frontend
            const role = document.getElementById('widget-role').value;
            if (role !== "manager" && role !== "admin") {
                tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="color: var(--danger); font-weight: 500;">Access Denied: Only Manager or Admin role can access HITL reviews.</td></tr>`;
                if (btn) {
                    btn.disabled = false;
                    btn.innerText = "🔄 Fetch Pending";
                }
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.innerText = "🔄 Fetching...";
            }
            
            try {
                const response = await fetch('/api/v1/triage', {
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    }
                });

                if(!response.ok) {
                    let errMsg = `HTTP error ${response.status} ${response.statusText}`;
                    try {
                        const errData = await response.json();
                        if (errData && errData.detail) {
                            errMsg += ` - ${errData.detail}`;
                        } else if (errData && errData.error) {
                            errMsg += ` - ${errData.error}`;
                        }
                    } catch(_) {}
                    throw new Error(errMsg);
                }

                const tickets = await response.json();
                const hitlTickets = tickets.filter(t => t.status === 'hitl');

                if(hitlTickets.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No tickets pending HITL review.</td></tr>`;
                    if (btn) {
                        btn.disabled = false;
                        btn.innerText = "🔄 Refresh List";
                    }
                    return;
                }

                tbody.innerHTML = "";
                hitlTickets.forEach(t => {
                    const tr = document.createElement('tr');
                    const textSnip = t.masked_text ? (t.masked_text.slice(0, 50) + "...") : (t.text.slice(0, 50) + "...");
                    
                    const violations = t.constitutional_violations && t.constitutional_violations.length > 0 
                        ? t.constitutional_violations.map(v => `${v.rule_id || v.rule}: ${v.reason || v.explanation || 'Safety policy trigger'}`).join(", ")
                        : "PII protection warning / Policy trigger";

                    tr.innerHTML = `
                        <td style="font-family: monospace;">${t.ticket_id.slice(0, 8)}...</td>
                        <td>${t.customer_id}</td>
                        <td title="${t.text}">${textSnip}</td>
                        <td style="color: var(--warning); font-weight: 500;">${violations}</td>
                        <td>
                            <button class="btn btn-success" style="padding: 4px 8px; font-size: 11px;" onclick="resumeHITLTicket('${t.ticket_id}')">🤝 Resume</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
                if (btn) {
                    btn.disabled = false;
                    btn.innerText = "🔄 Refresh List";
                }
            } catch(e) {
                console.error("Load HITL list failed", e);
                let displayMsg = "Failed to load HITL reviews. The server or database may be unreachable.";
                if (e.message.includes("403")) {
                    displayMsg = "Access Denied: Only Manager or Admin role can access HITL reviews.";
                } else if (e.message.includes("401")) {
                    displayMsg = "Authentication Failed: Session token has expired or is invalid.";
                }
                tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="color: var(--danger); font-weight: 500;">${displayMsg}<br><span style="font-size: 12px; font-family: monospace; color: var(--text-muted); display: block; margin-top: 8px;">${e.message}</span></td></tr>`;
                if (btn) {
                    btn.disabled = false;
                    btn.innerText = "🔄 Fetch Pending";
                }
            }
        }

        // Resume HITL Ticket
        async function resumeHITLTicket(ticketId) {
            const operatorId = prompt("Enter operator ID (e.g. operator_12):", "op_manager_01");
            if(!operatorId) return;
            const resolution = prompt("Enter manual override resolution text:", "Manual Override: Resolved and updated details.");
            if(!resolution) return;

            try {
                const response = await fetch(`/api/v1/triage/${ticketId}/resume`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${currentToken}`
                    },
                    body: JSON.stringify({
                        ticket_id: ticketId,
                        operator_id: operatorId,
                        resolution_override: resolution
                    })
                });

                if (response.status === 403) {
                    showToast("Access Denied: Only Manager or Admin role can resume HITL", true);
                    return;
                }

                if(!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Error resuming ticket");
                }

                showToast(`Ticket ${ticketId.slice(0, 8)} resumed successfully!`);
                loadHITLList();
            } catch(e) {
                console.error("Resume failed", e);
                showToast(e.message || "Failed to resume ticket", true);
            }
        }

        // Check system health
        async function checkSystemHealth() {
            try {
                const response = await fetch('/api/v1/ready');
                const data = await response.json();
                
                // Redis
                const redisEl = document.getElementById('health-redis');
                const redisConnected = data.services.redis === "ok";
                redisEl.innerText = redisConnected ? "Connected" : "Offline";
                redisEl.className = redisConnected ? "status-badge ok" : "status-badge error";

                // Redpanda
                const pandaEl = document.getElementById('health-redpanda');
                const redpandaActive = data.services.redpanda === "ok";
                pandaEl.innerText = redpandaActive ? "Active" : "Serverless Mode (Active Fallback)";
                pandaEl.className = redpandaActive ? "status-badge ok" : "status-badge info";
                pandaEl.title = redpandaActive ? "Redpanda event broker is online" : "Broker is offline in serverless space; system gracefully fell back to FastAPI BackgroundTasks.";

                // Supabase
                const subaEl = document.getElementById('health-supabase');
                const supabaseConnected = data.services.supabase === "ok";
                subaEl.innerText = supabaseConnected ? "Connected" : "Offline";
                subaEl.className = supabaseConnected ? "status-badge ok" : "status-badge error";

                // Config log
                let configText = `[CustomerCore Microservice Configuration Settings]\n`;
                configText += `- Active Environment: production\n`;
                configText += `- Database Stack: Supabase PostgreSQL (Row-Level Security active)\n`;
                configText += `- Caching: Redis Cache Store (Rate limits + L1 cache active)\n`;
                configText += `- Streaming Message Queue: Redpanda (Offline in cloud space, auto falling back to in-process async background tasks)\n`;
                configText += `- Multi-tenant Hybrid RAG: ChromaDB (Vector Search) + BM25 (Keyword Search) + Reciprocal Rank Fusion\n`;
                document.getElementById('health-config-log').innerText = configText;
            } catch(e) {
                showToast("Failed to fetch service health", true);
                document.getElementById('health-redis').innerText = "Unreachable";
                document.getElementById('health-redis').className = "status-badge error";
                document.getElementById('health-redpanda').innerText = "Unreachable";
                document.getElementById('health-redpanda').className = "status-badge error";
                document.getElementById('health-supabase').innerText = "Unreachable";
                document.getElementById('health-supabase').className = "status-badge error";
            }
        }

        // Automatically adjust select box width based on text length
        function adjustSelectWidth(selectEl) {
            if (!selectEl) return;
            const tempSpan = document.createElement("span");
            tempSpan.style.visibility = "hidden";
            tempSpan.style.position = "absolute";
            tempSpan.style.whiteSpace = "pre";
            
            const style = window.getComputedStyle(selectEl);
            tempSpan.style.fontFamily = style.fontFamily;
            tempSpan.style.fontSize = style.fontSize;
            tempSpan.style.fontWeight = style.fontWeight;
            tempSpan.style.letterSpacing = style.letterSpacing;
            
            const selectedText = selectEl.options[selectEl.selectedIndex].text;
            tempSpan.innerText = selectedText;
            document.body.appendChild(tempSpan);
            
            const textWidth = tempSpan.getBoundingClientRect().width;
            selectEl.style.width = (textWidth + 36) + "px"; // 36px accounts for arrow padding
            
            document.body.removeChild(tempSpan);
        }

        // Initialize Page
        window.addEventListener('DOMContentLoaded', () => {
            loadPreset('billing');
            setTimeout(() => {
                adjustSelectWidth(document.getElementById('widget-tenant'));
                adjustSelectWidth(document.getElementById('widget-role'));
            }, 100);
        });
    </script>
</body>
</html>
"""
