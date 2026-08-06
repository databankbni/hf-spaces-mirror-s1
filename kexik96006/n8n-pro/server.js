const express = require('express');
const app = express();

// Hugging Face ke liye 7860 port zaroori ha
const PORT = 7860; 

// Hardcoded List of Users
const users = [
    { 
        id: 1, 
        name: "Ali Raza", 
        father_name: "Ahmad Raza", 
        email: "ali@example.com", 
        password: "password123" 
    },
    { 
        id: 2, 
        name: "Usman Khan", 
        father_name: "Tariq Khan", 
        email: "usman@example.com", 
        password: "securepass456" 
    },
    { 
        id: 3, 
        name: "Zainab", 
        father_name: "Nadeem", 
        email: "zainab@example.com", 
        password: "mypassword789" 
    }
];

// API 1: Get All Users
app.get('/api/users', (req, res) => {
    res.json({
        success: true,
        total_users: users.length,
        data: users
    });
});

// API 2: Get User by ID
app.get('/api/users/:id', (req, res) => {
    // URL se id nikal kar integer mein convert karein
    const userId = parseInt(req.params.id); 
    const user = users.find(u => u.id === userId);

    if (user) {
        res.json({ success: true, data: user });
    } else {
        res.status(404).json({ success: false, message: "User not found" });
    }
});

// Default route (agar base URL hit ho)
app.get('/', (req, res) => {
    res.send("Hugging Face API is running! Go to /api/users to see data.");
});

// Server Start
app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});