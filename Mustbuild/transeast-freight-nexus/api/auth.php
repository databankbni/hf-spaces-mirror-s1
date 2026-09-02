<?php
header('Content-Type: application/json');
require_once '../config/database.php';
session_start();

// Handle authentication requests
$action = $_POST['action'] ?? '';

switch($action) {
    case 'login':
        handleLogin();
        break;
    case 'register':
        handleRegister();
        break;
    case 'google_login':
        handleGoogleLogin();
        break;
    case 'logout':
        handleLogout();
        break;
    default:
        echo json_encode(['success' => false, 'message' => 'Invalid action']);
}

function handleRegister() {
    $email = filter_var($_POST['email'], FILTER_SANITIZE_EMAIL);
    $password = $_POST['password'] ?? '';
    $firstName = $_POST['first_name'] ?? '';
    $lastName = $_POST['last_name'] ?? '';
    $userType = $_POST['user_type'] ?? 'user';
    $companyName = $_POST['company_name'] ?? '';
    
    $db = Database::getInstance()->getConnection();
    
    // Check if email already exists
    $stmt = $db->prepare("SELECT id FROM users WHERE email = ?");
    $stmt->execute([$email]);
    if ($stmt->fetch()) {
        echo json_encode(['success' => false, 'message' => 'Email already registered']);
        return;
    }
    
    // Hash password
    $passwordHash = password_hash($password, PASSWORD_BCRYPT);
    
    // Insert user
    $stmt = $db->prepare("INSERT INTO users (email, password_hash, first_name, last_name, user_type, company_name, account_status) VALUES (?, ?, ?, ?, ?, ?, 'active')");
    $stmt->execute([$email, $passwordHash, $firstName, $lastName, $userType, $companyName]);
    $userId = $db->lastInsertId();
    
    // Create profile based on user type
    switch($userType) {
        case 'broker':
            $stmt = $db->prepare("INSERT INTO broker_profiles (user_id, company_name) VALUES (?, ?)");
            $stmt->execute([$userId, $companyName]);
            break;
        case 'carrier':
            $stmt = $db->prepare("INSERT INTO carrier_profiles (user_id, company_name) VALUES (?, ?)");
            $stmt->execute([$userId, $companyName]);
            break;
        case 'shipper':
            $stmt = $db->prepare("INSERT INTO shipper_profiles (user_id, company_name) VALUES (?, ?)");
            $stmt->execute([$userId, $companyName]);
            break;
    }
    
    $_SESSION['user_id'] = $userId;
    $_SESSION['user_type'] = $userType;
    $_SESSION['name'] = $firstName . ' ' . $lastName;
    
    echo json_encode([
        'success' => true,
        'user_type' => $userType,
        'redirect' => getRedirectByType($userType),
        'user_id' => $userId
    ]);
}

function handleLogin() {
    $email = filter_var($_POST['email'], FILTER_SANITIZE_EMAIL);
    $password = $_POST['password'] ?? '';
    $login_type = $_POST['login_type'] ?? '';
    
    $db = Database::getInstance()->getConnection();
    
    // If login_type specified, verify user type matches
    if ($login_type) {
        $stmt = $db->prepare("SELECT id, password_hash, user_type, first_name, last_name, account_status FROM users WHERE email = ? AND user_type = ?");
        $stmt->execute([$email, $login_type]);
    } else {
        $stmt = $db->prepare("SELECT id, password_hash, user_type, first_name, last_name, account_status FROM users WHERE email = ?");
        $stmt->execute([$email]);
    }
    
    $user = $stmt->fetch();
    
    if ($user && $user['account_status'] !== 'active') {
        echo json_encode(['success' => false, 'message' => 'Account is not active. Please verify your email or contact support.']);
        return;
    }
    
    if ($user && password_verify($password, $user['password_hash'])) {
        $_SESSION['user_id'] = $user['id'];
        $_SESSION['user_type'] = $user['user_type'];
        $_SESSION['name'] = $user['first_name'] . ' ' . $user['last_name'];
        $_SESSION['email'] = $email;
        
        echo json_encode([
            'success' => true, 
            'user_type' => $user['user_type'],
            'redirect' => getRedirectByType($user['user_type']),
            'user_id' => $user['id']
        ]);
    } else {
        echo json_encode(['success' => false, 'message' => 'Invalid credentials']);
    }
}

function handleGoogleLogin() {
    $google_id = $_POST['google_id'] ?? '';
    $email = filter_var($_POST['email'], FILTER_SANITIZE_EMAIL);
    $name = $_POST['name'] ?? '';
    
    $db = Database::getInstance()->getConnection();
    
    // Check if user exists
    $stmt = $db->prepare("SELECT id, user_type FROM users WHERE google_id = ? OR email = ?");
    $stmt->execute([$google_id, $email]);
    $user = $stmt->fetch();
    
    if ($user) {
        $_SESSION['user_id'] = $user['id'];
        $_SESSION['user_type'] = $user['user_type'];
        echo json_encode(['success' => true, 'user_type' => $user['user_type']]);
    } else {
        // New user - need to select account type
        $nameParts = explode(' ', $name, 2);
        $stmt = $db->prepare("INSERT INTO users (google_id, email, first_name, last_name) VALUES (?, ?, ?, ?)");
        $stmt->execute([$google_id, $email, $nameParts[0], $nameParts[1] ?? '']);
        $_SESSION['user_id'] = $db->lastInsertId();
        
        echo json_encode(['success' => true, 'new_user' => true]);
    }
}

function handleLogout() {
    session_destroy();
    echo json_encode(['success' => true]);
}

function getRedirectByType($type) {
    switch($type) {
        case 'carrier':
            return '/dashboard-carrier.html';
        case 'broker':
            return '/dashboard-broker.html';
        case 'shipper':
            return '/dashboard-shipper.html';
        case 'government':
            return '/dashboard-government.html';
        case 'admin':
            return '/admin-dashboard.html';
        default:
            return '/dashboard.html';
    }
}