---
title: Heaven on Earth Kingdom CMS Backend
emoji: 🕊
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Heaven on Earth CMS Backend

A robust and secure Content Management System (CMS) backend, meticulously crafted to power the Heaven on Earth Kingdom Family Ministries web platform. This service provides a comprehensive suite of APIs for managing all aspects of the ministry's digital content, from events and ministries to prayer requests and partnerships.

## Key Feature

*   **Comprehensive Content Management:** Full CRUD (Create, Read, Update, Delete) operations for:
    *   **Admins:** Securely manage CMS users, including invitation and role-based access (superadmin privileges).
    *   **Events:** Organize and publish church events with details like date, time, location, category, and featured status.
    *   **Ministries:** Define and manage various ministry departments, including their leaders, activities, and schedules.
    *   **Gallery Items:** Upload and manage images and videos, categorizing them for the public gallery.
    *   **Prayer Requests:** Receive, review, respond to, and track prayer requests from the community.
    *   **Testimonials:** Moderate, approve, and publish inspiring testimonies from members.
    *   **Partnership Applications:** Handle inquiries for financial, volunteer, and material partnerships.
*   **Robust Authentication & Authorization:** Implements JWT-based authentication with secure access and refresh tokens, ensuring only authorized administrators can access sensitive endpoints. Role-based access control (e.g., superadmin) is integrated for granular permissions.
*   **Secure File Storage:** Seamless integration with Supabase Storage for efficient and scalable management of all media assets (images, videos) associated with gallery items.
*   **Bilingual Content Support:** Models and schemas are designed to support content in both English and Amharic, facilitating a localized experience for the frontend.
*   **Data Integrity & Persistence:** Utilizes PostgreSQL as the primary data store, ensuring high availability, reliability, and data integrity.
*   **Scalable & High-Performance API:** Built with FastAPI, leveraging Python's asynchronous capabilities for fast and efficient request processing.
*   **Automated Database Migrations:** Manages database schema changes effortlessly using Alembic, ensuring consistency across development and production environments.
*   **Enhanced Security Measures:** Includes password hashing (bcrypt), rate limiting to prevent abuse, configurable CORS policies, and comprehensive input validation using Pydantic.
*   **Self-Documenting API:** Automatically generates interactive API documentation (Swagger UI and ReDoc) for easy exploration and testing of endpoints.

## Project Structure

The backend is organized into logical modules to promote maintainability and scalability:

```
backend/
├── app/
│   ├── api/v1/endpoints/    # Defines all API routes and their handlers
│   ├── crud/                # Database interaction logic (Create, Read, Update, Delete)
│   ├── models/              # SQLAlchemy ORM models defining database tables
│   ├── schemas/             # Pydantic schemas for data validation and serialization
│   ├── utils/               # Utility functions (e.g., Supabase integration)
│   ├── config.py            # Centralized application configuration
│   ├── database.py          # Database connection and session management
│   ├── dependencies.py      # FastAPI dependency injection for common tasks (e.g., auth, DB session)
│   ├── security.py          # JWT token handling and password hashing utilities
│   └── main.py              # Main FastAPI application entry point
├── alembic/                 # Alembic migration scripts and configuration
├── .env.example             # Template for environment variables
├── requirements.txt         # Python package dependencies
└── README.md                # This documentation file
```

## Getting Started

Follow these steps to set up and run the Heaven on Earth CMS Backend on your local machine.

### Prerequisites

Ensure you have the following installed:

*   **Python 3.11+**: Download from [python.org](https://www.python.org/downloads/).
*   **PostgreSQL 14+**: Install via your operating system's package manager or download from [postgresql.org](https://www.postgresql.org/download/).
*   **`pip` or `poetry`**: Python package manager (pip is usually included with Python).

### Installation

1.  **Clone the repository and navigate to the backend directory:**

    ```bash
    git clone https://github.com/dagiteferi/kingdom_web.git
    cd kingdom_web/backend
    ```

2.  **Create and activate a Python virtual environment:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Linux/macOS
    # venv\Scripts\activate    # On Windows
    ```

3.  **Install Python dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables:**

    Copy the example environment file and populate it with your specific settings. This includes database connection details, Supabase credentials, and JWT secrets.

    ```bash
    cp .env.example .env
    # Open .env in your editor and fill in the required values.
    ```

    **Important `.env` variables:**
    *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql+asyncpg://user:password@host:port/database_name`).
    *   `SUPABASE_URL`: Your Supabase project URL.
    *   `SUPABASE_KEY`: Your Supabase `anon` or `service_role` key.
    *   `JWT_SECRET_KEY`: A strong, random secret key for JWT signing (min. 32 characters).
    *   `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_FULL_NAME`: Credentials for the initial super admin user (created on first startup if no admins exist).

5.  **Create your PostgreSQL database:**

    ```bash
    createdb heavenonearth_cms
    ```
    (Replace `heavenonearth_cms` with your desired database name if different from `.env`.)

6.  **Run database migrations:**

    Apply the database schema using Alembic.

    ```bash
    alembic upgrade head
    ```

### Running the Server

Choose the appropriate command based on your environment:

*   **Development (with auto-reload):**

    ```bash
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```

*   **Production (using Gunicorn for robustness):**

    ```bash
    gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
    ```

    The API will be accessible at `http://localhost:8000`.

## Deployment

For production deployments, it is recommended to containerize the application using Docker and deploy it to a cloud platform.

1.  **Dockerization:** A `Dockerfile` is provided in the root of the `backend` directory to build a Docker image of the application.
2.  **Environment Variables:** Ensure all necessary environment variables (as listed in `.env.example`) are securely configured in your deployment environment.
3.  **Gunicorn:** The production command uses Gunicorn to serve the FastAPI application, providing robustness and concurrency.
4.  **Database:** Ensure your PostgreSQL database is accessible from your deployed application.

## API Documentation

Once the server is running, interactive API documentation is automatically generated and available at:

*   **Swagger UI:** `http://localhost:8000/docs`
*   **ReDoc:** `http://localhost:8000/redoc`

These interfaces allow you to explore available endpoints, understand request/response schemas, and test API calls directly from your browser.

## Security Considerations

Security is paramount for our CMS. The backend incorporates several measures:

*   **Environment Variable Management:** All sensitive configurations (database credentials, API keys, JWT secrets) are loaded from environment variables, never hardcoded.
*   **Password Hashing:** User passwords are securely hashed using `bcrypt` with adaptive rounds, preventing plaintext storage.
*   **JWT Authentication:** Implements a robust JWT system with distinct access and refresh tokens, short-lived access tokens, and token invalidation mechanisms.
*   **Rate Limiting:** Protects against brute-force attacks and API abuse by limiting the number of requests from a single source.
*   **CORS Configuration:** Strictly controls which origins are allowed to access the API, mitigating cross-site scripting (XSS) risks.
*   **Input Validation:** All incoming data is rigorously validated using Pydantic schemas, ensuring data integrity and preventing common injection vulnerabilities.

## Testing

To run the test suite and ensure all components are functioning as expected:

```bash
pytest --cov=app tests/
```

## API Endpoints Overview

The API is versioned under `/api/v1` and provides the following endpoint groups:

### Authentication

*   `POST /api/v1/auth/login`: Authenticate an administrator and receive JWT access and refresh tokens.
*   `POST /api/v1/auth/refresh`: Obtain a new access token using a valid refresh token.
*   `POST /api/v1/auth/logout`: Invalidate the current session's tokens (client-side deletion).

### Admin Management

*   `GET /api/v1/admins`: Retrieve a paginated list of all administrators (superadmin only).
*   `POST /api/v1/admins/invite`: Send an invitation to a new administrator (superadmin only).
*   `GET /api/v1/admins/me`: Retrieve the profile of the currently authenticated administrator.
*   `PUT /api/v1/admins/me`: Update the profile of the currently authenticated administrator.
*   `GET /api/v1/admins/{admin_id}`: Fetch details of a specific administrator by ID (superadmin only).
*   `DELETE /api/v1/admins/{admin_id}`: Deactivate an administrator account (superadmin only).

### Events

*   `GET /api/v1/events`: List all events with optional filtering and pagination.
*   `POST /api/v1/events`: Create a new event (admin only).
*   `GET /api/v1/events/{event_id}`: Retrieve details of a specific event by ID.
*   `PUT /api/v1/events/{event_id}`: Update an existing event (admin only).
*   `DELETE /api/v1/events/{event_id}`: Delete an event (admin only).

### Ministries

*   `GET /api/v1/ministries`: List all ministries with optional filtering and pagination.
*   `POST /api/v1/ministries`: Create a new ministry (admin only).
*   `GET /api/v1/ministries/{ministry_id_or_key}`: Retrieve details of a specific ministry by ID or unique key.
*   `PUT /api/v1/ministries/{ministry_id}`: Update an existing ministry (admin only).
*   `DELETE /api/v1/ministries/{ministry_id}`: Delete a ministry (admin only).

### Gallery

*   `GET /api/v1/gallery`: List all gallery items (images/videos) with optional filtering and pagination.
*   `POST /api/v1/gallery`: Create a new gallery item by uploading a file (admin only).
*   `POST /api/v1/gallery/url`: Create a new gallery item using a direct URL (admin only).
*   `GET /api/v1/gallery/{item_id}`: Retrieve details of a specific gallery item by ID.
*   `PUT /api/v1/gallery/{item_id}`: Update an existing gallery item (admin only).
*   `DELETE /api/v1/gallery/{item_id}`: Delete a gallery item and its associated files from storage (admin only).

### Prayer Requests

*   `GET /api/v1/prayers`: List all prayer requests with optional filtering and pagination.
*   `POST /api/v1/prayers`: Submit a new prayer request (public endpoint).
*   `GET /api/v1/prayers/{prayer_id}`: Retrieve details of a specific prayer request by ID (admin only).
*   `PUT /api/v1/prayers/{prayer_id}`: Update a prayer request (admin only).
*   `POST /api/v1/prayers/{prayer_id}/respond`: Log an admin response to a prayer request (admin only).
*   `POST /api/v1/prayers/{prayer_id}/pray`: Increment the 'I prayed' count for a request (public endpoint).
*   `DELETE /api/v1/prayers/{prayer_id}`: Delete a prayer request (admin only).

### Testimonials

*   `GET /api/v1/testimonials`: List all testimonials with optional filtering and pagination.
*   `POST /api/v1/testimonials`: Submit a new testimonial (public endpoint).
*   `GET /api/v1/testimonials/{testimonial_id}`: Retrieve details of a specific testimonial by ID.
*   `PUT /api/v1/testimonials/{testimonial_id}`: Update a testimonial (admin only).
*   `POST /api/v1/testimonials/{testimonial_id}/review`: Approve or reject a testimonial (admin only).
*   `DELETE /api/v1/testimonials/{testimonial_id}`: Delete a testimonial (admin only).

### Partnerships

*   `GET /api/v1/partnerships`: List all partnership applications with optional filtering and pagination (admin only).
*   `POST /api/v1/partnerships`: Submit a new partnership application (public endpoint).
*   `GET /api/v1/partnerships/{partnership_id}`: Retrieve details of a specific partnership application by ID (admin only).
*   `PUT /api/v1/partnerships/{partnership_id}`: Update a partnership application (admin only).
*   `POST /api/v1/partnerships/{partnership_id}/contact`: Log contact with a potential partner (admin only).
*   `DELETE /api/v1/partnerships/{partnership_id}`: Delete a partnership application (admin only).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file in the root directory for full details.

## Contributing

We welcome contributions! If you're interested in improving this backend service, please refer to the main [GitHub repository](https://github.com/dagiteferi/kingdom_web) for contribution guidelines, issue reporting, and feature requests.

---
_This documentation aims to provide a clear and comprehensive guide for developers working with the Heaven on Earth CMS Backend._
