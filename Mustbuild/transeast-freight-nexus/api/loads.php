<?php
header('Content-Type: application/json');
require_once '../config/database.php';
session_start();

// Check authentication
if (!isset($_SESSION['user_id'])) {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized']);
    exit;
}

$db = Database::getInstance()->getConnection();
$method = $_SERVER['REQUEST_METHOD'];

switch($method) {
    case 'GET':
        // Get loads with filters
        $where = [];
        $params = [];
        
        if (isset($_GET['origin'])) {
            $where[] = "origin_city LIKE ?";
            $params[] = '%' . $_GET['origin'] . '%';
        }
        if (isset($_GET['destination'])) {
            $where[] = "destination_city LIKE ?";
            $params[] = '%' . $_GET['destination'] . '%';
        }
        if (isset($_GET['equipment'])) {
            $where[] = "equipment_type = ?";
            $params[] = $_GET['equipment'];
        }
        
        $sql = "SELECT l.*, u.company_name as broker_company 
                FROM load_posts l 
                JOIN users u ON l.broker_id = u.id 
                WHERE l.status = 'open'";
        
        if ($where) {
            $sql .= " AND " . implode(" AND ", $where);
        }
        
        $sql .= " ORDER BY l.created_at DESC LIMIT 50";
        
        $stmt = $db->prepare($sql);
        $stmt->execute($params);
        $loads = $stmt->fetchAll();
        
        echo json_encode(['success' => true, 'loads' => $loads]);
        break;
        
    case 'POST':
        // Create new load (broker only)
        $data = json_decode(file_get_contents('php://input'), true);
        
        $stmt = $db->prepare("INSERT INTO load_posts (broker_id, origin_city, origin_state, origin_country, 
                              destination_city, destination_state, destination_country, equipment_type, 
                              weight_lbs, freight_type, rate, pickup_date, delivery_date, description) 
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
        
        $stmt->execute([
            $_SESSION['user_id'],
            $data['origin_city'],
            $data['origin_state'],
            $data['origin_country'],
            $data['destination_city'],
            $data['destination_state'],
            $data['destination_country'],
            $data['equipment_type'],
            $data['weight_lbs'],
            $data['freight_type'],
            $data['rate'],
            $data['pickup_date'],
            $data['delivery_date'],
            $data['description']
        ]);
        
        echo json_encode(['success' => true, 'load_id' => $db->lastInsertId()]);
        break;
}