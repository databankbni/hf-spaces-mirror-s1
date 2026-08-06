# Cloudflare Pages Deployment

This frontend is a static Vite app, so it can be deployed to Cloudflare Pages without any adapter.

1. Push the `frontend` folder to a GitHub repository.
2. In Cloudflare Dashboard, create a new Pages project and connect that GitHub repo.
3. Set the build command to `npm run build`.
4. Set the output directory to `dist`.
5. Optional: add a `VITE_BACKEND_URL` environment variable in Cloudflare Pages if you want the app to point to a specific API URL by default.
6. Deploy the project. Cloudflare Pages will serve the frontend at a public `*.pages.dev` URL.

Notes:

- The frontend still lets you override the API endpoint from the UI.
- The backend must be publicly reachable from the browser if you want the Analyze button to work on the deployed site.
