-- TransEast Freight Nexus Database Schema
-- This would be run on a MySQL/PostgreSQL server

CREATE DATABASE IF NOT EXISTS transeast_freight;
USE transeast_freight;

-- Users table with role separation
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    user_type ENUM('broker', 'carrier', 'shipper', 'government', 'admin', 'user') NOT NULL DEFAULT 'user',
    company_name VARCHAR(255),
    phone VARCHAR(50),
    account_status ENUM('active', 'pending', 'suspended', 'deleted') DEFAULT 'pending',
    email_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_user_type (user_type),
    INDEX idx_google_id (google_id),
    INDEX idx_account_status (account_status)
);

-- Broker profiles (for shippers/brokers who post loads)
CREATE TABLE broker_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    company_name VARCHAR(255),
    mc_number VARCHAR(50) UNIQUE,
    dot_number VARCHAR(50) UNIQUE,
    tax_id VARCHAR(50),
    years_in_business INT,
    bonded BOOLEAN DEFAULT FALSE,
    credit_score INT,
    verified BOOLEAN DEFAULT FALSE,
    business_address TEXT,
    business_phone VARCHAR(50),
    business_email VARCHAR(255),
    preferred_payment_method VARCHAR(50),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Carrier profiles (transporters who move loads)
CREATE TABLE carrier_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    company_name VARCHAR(255),
    mc_number VARCHAR(50) UNIQUE,
    dot_number VARCHAR(50) UNIQUE,
    tax_id VARCHAR(50),
    fleet_size INT DEFAULT 0,
    equipment_types TEXT,
    insurance_provider VARCHAR(255),
    insurance_policy_number VARCHAR(100),
    insurance_expiry DATE,
    insurance_verified BOOLEAN DEFAULT FALSE,
    safety_rating VARCHAR(10),
    operating_authority VARCHAR(100),
    operating_regions TEXT,
    verified BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Shipper profiles (regular users who ship goods)
CREATE TABLE shipper_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    company_name VARCHAR(255),
    business_type VARCHAR(100),
    shipping_volume VARCHAR(50),
    preferred_routes TEXT,
    business_address TEXT,
    business_phone VARCHAR(50),
    verified BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Broker profiles
CREATE TABLE broker_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    company_name VARCHAR(255),
    mc_number VARCHAR(50),
    dot_number VARCHAR(50),
    years_in_business INT,
    bonded BOOLEAN DEFAULT FALSE,
    credit_score INT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Carrier profiles
CREATE TABLE carrier_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    company_name VARCHAR(255),
    mc_number VARCHAR(50),
    dot_number VARCHAR(50),
    fleet_size INT DEFAULT 0,
    equipment_types TEXT,
    insurance_verified BOOLEAN DEFAULT FALSE,
    safety_rating VARCHAR(10),
    operating_authority VARCHAR(100),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Government official profiles
CREATE TABLE government_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    agency_name VARCHAR(255),
    department VARCHAR(255),
    badge_number VARCHAR(50),
    clearance_level VARCHAR(50),
    jurisdiction TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Load board posts
CREATE TABLE load_posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    broker_id INT NOT NULL,
    origin_city VARCHAR(255),
    origin_state VARCHAR(100),
    origin_country VARCHAR(100),
    destination_city VARCHAR(255),
    destination_state VARCHAR(100),
    destination_country VARCHAR(100),
    equipment_type VARCHAR(100),
    weight_lbs DECIMAL(10,2),
    freight_type VARCHAR(100),
    rate DECIMAL(10,2),
    pickup_date DATE,
    delivery_date DATE,
    status ENUM('open', 'assigned', 'in_transit', 'delivered', 'cancelled') DEFAULT 'open',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (broker_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_status (status),
    INDEX idx_origin (origin_city, origin_state),
    INDEX idx_destination (destination_city, destination_state)
);

-- Shipments/Tracking
CREATE TABLE shipments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    load_id INT NOT NULL,
    carrier_id INT NOT NULL,
    tracking_number VARCHAR(50) UNIQUE,
    current_location VARCHAR(255),
    estimated_delivery TIMESTAMP,
    actual_delivery TIMESTAMP,
    status ENUM('assigned', 'picked_up', 'in_transit', 'at_checkpoint', 'delayed', 'delivered') DEFAULT 'assigned',
    FOREIGN KEY (load_id) REFERENCES load_posts(id),
    FOREIGN KEY (carrier_id) REFERENCES users(id),
    INDEX idx_tracking (tracking_number),
    INDEX idx_carrier (carrier_id)
);

-- Fleet management
CREATE TABLE fleet_vehicles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    carrier_id INT NOT NULL,
    vehicle_type VARCHAR(100),
    make VARCHAR(100),
    model VARCHAR(100),
    year INT,
    vin VARCHAR(50) UNIQUE,
    license_plate VARCHAR(50),
    registration_expiry DATE,
    insurance_expiry DATE,
    last_maintenance DATE,
    status ENUM('active', 'maintenance', 'out_of_service', 'sold') DEFAULT 'active',
    gps_device_id VARCHAR(100),
    FOREIGN KEY (carrier_id) REFERENCES users(id),
    INDEX idx_carrier (carrier_id),
    INDEX idx_status (status)
);

-- Driver management
CREATE TABLE drivers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    carrier_id INT NOT NULL,
    vehicle_id INT,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    license_number VARCHAR(50),
    license_expiry DATE,
    medical_cert_expiry DATE,
    phone VARCHAR(50),
    email VARCHAR(255),
    status ENUM('active', 'on_leave', 'suspended', 'terminated') DEFAULT 'active',
    FOREIGN KEY (carrier_id) REFERENCES users(id),
    FOREIGN KEY (vehicle_id) REFERENCES fleet_vehicles(id),
    INDEX idx_carrier (carrier_id)
);

-- Documents
CREATE TABLE documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    document_type VARCHAR(100),
    file_path VARCHAR(500),
    expiry_date DATE,
    verified BOOLEAN DEFAULT FALSE,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Messages/Communication
CREATE TABLE messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sender_id INT NOT NULL,
    receiver_id INT NOT NULL,
    load_id INT,
    subject VARCHAR(255),
    message TEXT,
    read BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id),
    FOREIGN KEY (load_id) REFERENCES load_posts(id)
);