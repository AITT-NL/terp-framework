# Frontend image (Vite dev server) for the workbench. Built from the repo root
# (docker-compose.yml sets `context: .`) so the whole frontend/ tree is available.
FROM node:24-slim

WORKDIR /app

# Preserve the project tree shape (frontend/ plus the optional .terp-dist/ of
# pre-release @terp tarballs vendored by Terp Studio): file: refs recorded in
# package.json resolve inside the image exactly as they do on the host.
COPY . .
WORKDIR /app/frontend
RUN npm install

EXPOSE 5173
# The Vite dev server, reachable from the host; the /api proxy target is TERP_API_PROXY
# (set to the api service in compose), so the browser calls the API same-origin.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
