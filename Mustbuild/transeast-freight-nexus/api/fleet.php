<?php
header('Content-Type: application/json');
require_once '../config/database.php';
session_start();

if (!isset($_SESSION['user_id']) || $_SESSION['user_type'] !== 'carrier') {
    http_response_code(403);
    echo json_encode(['error' => 'Forbidden']);
    exit;
}

$db = Database::getInstance()->getConnection();
$method = $_SERVER['REQUEST_METHOD'];

switch($method) {
    case 'GET':
        $action = $_GET['action'] ?? 'vehicles';
        
        if ($action === 'vehicles') {
            $stmt = $db->prepare("SELECT * FROM fleet_vehicles WHERE carrier_id = ?");
            $stmt->execute([$_SESSION['user_id']]);
            echo json_encode(['vehicles' => $stmt->fetchAll()]);
        } elseif ($action === 'drivers') {
            $stmt = $db->prepare("SELECT d.*, v.make, v.model, v.license_plate 
                                  FROM drivers d 
                                  LEFT JOIN fleet_vehicles v ON d.vehicle_id = v.id 
                                  WHERE d.carrier_id = ?");
            $stmt->execute([$_SESSION['user_id']]);
            echo json_encode(['drivers' => $stmt->fetchAll()]);
        }
        break;
        
    case 'POST':
        $data = json_decode(file_get_contents('php://input'), true);
        $type = $data['type'] ?? 'vehicle';
        
        if ($type === 'vehicle') {
            $stmt = $db->prepare("INSERT INTO fleet_vehicles (carrier_id, vehicle_type, make, model, year, vin, license_plate) 
                                  VALUES (?, ?, ?, ?, ?, ?, ?)");
            $stmt->execute([$_SESSION['user_id'], $data['vehicle_type'], $data['make'], $data['model'], 
                           $data['year'], $data['vin'], $data['license_plate']]);
        } elseif ($type === 'driver') {
            $stmt = $db->prepare("INSERT INTO drivers (carrier_id, vehicle_id, first_name, last_name, license_number, phone, email) 
                                  VALUES (?, ?, ?, ?, ?, ?, ?)");
            $stmt->execute([$_SESSION['user_id'], $data['vehicle_id'], $data['first_name'], 
                           $data['last_name'], $data['license_number'], $data['phone'], $data['email']]);
        }
        
        echo json_encode(['success' => true, 'id' => $db->lastInsertId()]);
        break;
}