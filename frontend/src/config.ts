// Single place to change the backend URL instead of hunting through
// every component. Override with VITE_API_URL in a .env file if your
// backend runs somewhere other than localhost:5000.
export const API_BASE_URL: string = import.meta.env.VITE_API_URL || "http://localhost:5000";