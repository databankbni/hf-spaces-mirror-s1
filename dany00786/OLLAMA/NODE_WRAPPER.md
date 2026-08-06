# OLLAMA Node.js Wrapper (Draft)

If you wish to use this infrastructure in a Node.js project, you can use the following example client based on `axios`.

## Installation

```bash
npm install axios
```

## Example Client

```javascript
const axios = require('axios');

class OllamaClient {
    constructor(baseUrl = 'http://localhost:11434') {
        this.baseUrl = baseUrl;
    }

    async listModels() {
        const response = await axios.get(`${this.baseUrl}/api/tags`);
        return response.data.models;
    }

    async generate(prompt, model = 'qwen2:0.5b') {
        const response = await axios.post(`${this.baseUrl}/api/generate`, {
            model,
            prompt,
            stream: false
        });
        return response.data;
    }

    async chat(messages, model = 'qwen2:0.5b') {
        const response = await axios.post(`${this.baseUrl}/api/chat`, {
            model,
            messages,
            stream: false
        });
        return response.data;
    }
}

// Usage
(async () => {
    const client = new OllamaClient();
    try {
        const models = await client.listModels();
        console.log('Available models:', models);

        const response = await client.generate('Why is the sky blue?');
        console.log('Response:', response.response);
    } catch (error) {
        console.error('Error:', error.message);
    }
})();
```

## Integrating with the Bridge

If using the bridge (port 8000), simply change the `baseUrl` to `http://localhost:8000`.
