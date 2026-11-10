"""AWS Lambda entrypoint (API Gateway HTTP API + Mangum)."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="auto")
