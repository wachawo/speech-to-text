DOCKER_BUILDKIT=1 docker compose up -d --build
DOCKER_BUILDKIT=1 docker compose build --no-cache
docker compose logs -f --tail=100
docker compose up -d cgevents_nginx --build --no-cache
