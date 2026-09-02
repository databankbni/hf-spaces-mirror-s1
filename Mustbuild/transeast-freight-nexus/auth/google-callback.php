<?php
session_start();
require_once '../config/database.php';
require_once 'google-config.php';

if (isset($_GET['code'])) {
    $token = $client->fetchAccessTokenWithAuthCode($_GET['code']);
    $client->setAccessToken($token['access_token']);
    
    // Get profile info
    $google_oauth = new Google_Service_Oauth2($client);
    $google_account_info = $google_oauth->userinfo->get();
    $email = $google_account_info->email;
    $name = $google_account_info->name;
    $google_id = $google_account_info->id;
    
    // Check if user exists
    $db = Database::getInstance()->getConnection();
    $stmt = $db->prepare("SELECT id, user_type FROM users WHERE email = ? OR google_id = ?");
    $stmt->execute([$email, $google_id]);
    $user = $stmt->fetch();
    
    if ($user) {
        // User exists - log them in
        $_SESSION['user_id'] = $user['id'];
        $_SESSION['user_type'] = $user['user_type'];
        $_SESSION['email'] = $email;
        $_SESSION['name'] = $name;
        
        // Update google_id if not set
        if (!$user['google_id']) {
            $stmt = $db->prepare("UPDATE users SET google_id = ? WHERE id = ?");
            $stmt->execute([$google_id, $user['id']]);
        }
        
        // Redirect to user type selection if not set
        if (!$user['user_type']) {
            header('Location: /select-account-type.html');
        } else {
            header('Location: /dashboard.html');
        }
    } else {
        // New user - store in session and redirect to account type selection
        $_SESSION['google_email'] = $email;
        $_SESSION['google_name'] = $name;
        $_SESSION['google_id'] = $google_id;
        
        header('Location: /select-account-type.html');
    }
    exit();
}