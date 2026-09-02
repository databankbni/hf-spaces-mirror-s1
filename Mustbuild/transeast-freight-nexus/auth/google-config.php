<?php
// Google OAuth Configuration
session_start();

require_once '../vendor/autoload.php'; // If using Composer for Google API

$client = new Google_Client();
$client->setClientId('YOUR_GOOGLE_CLIENT_ID');
$client->setClientSecret('YOUR_GOOGLE_CLIENT_SECRET');
$client->setRedirectUri('http://localhost/auth/google-callback.php');
$client->addScope('email');
$client->addScope('profile');

// Create Google Login URL
function getGoogleLoginUrl() {
    global $client;
    return $client->createAuthUrl();
}