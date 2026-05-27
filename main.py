import logging #para generar logs
import os #para leer Variables de entorno del sistema operativo
import random #numeros aleatorios
import time #manejar tiempos
from typing import Optional #declarar parámetros

import httpx # cliente para llamadas entre microservicios
import uvicorn #servidor ASGI para FastAPI
from fastapi import FastAPI, Response #framework web 
from opentelemetry.propagate import inject #OpenTelemetry para traces
from utils import PrometheusMiddleware, metrics, setting_otlp #middleware de prometheus, metricas y configuraciones de OTLP

APP_NAME = os.environ.get("APP_NAME", "app")
EXPOSE_PORT = os.environ.get("EXPOSE_PORT", 8000)
OTLP_GRPC_ENDPOINT = os.environ.get("OTLP_GRPC_ENDPOINT", "http://tempo:4317") #de aqui se exportan traces

TARGET_ONE_HOST = os.environ.get("TARGET_ONE_HOST", "app-b") #hosts de otros microservicios
TARGET_TWO_HOST = os.environ.get("TARGET_TWO_HOST", "app-c")

app = FastAPI() #se crea app ASGI FastAPI

#Este middleware:
#mide latencia
#cuenta requests
#cuenta errores
#genera métricas con Prometheus
app.add_middleware(PrometheusMiddleware, app_name=APP_NAME)
#Prometheus hará scraping aquí:
#GET /metrics
#fastapi_requests_total
#fastapi_responses_total
app.add_route("/metrics", metrics)
#OpenTelemetry
#instrumenta FastAPI
#genera traces/spans
#exporta traces a Tempo
#habilita correlación de logs
setting_otlp(app, APP_NAME, OTLP_GRPC_ENDPOINT)


#evita que aparezcan logs de GET/metrics, para no saturar los logs
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("GET /metrics") == -1

#logger de acceso HTTP de uvicorn
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

#endpoint que me generará error
@app.get("/")
async def read_root():
    logging.error("Hello World")
    return {"Hello": "World"}

#sinula peticiones mandando parámetros dinámicos
@app.get("/items/{item_id}")
async def read_item(item_id: int, q: Optional[str] = None):
    logging.error("items")
    return {"item_id": item_id, "q": q}

#simula tareas de duración, como tareas en disco, red, DB I/O bound
@app.get("/io_task")
async def io_task():
    time.sleep(1)
    logging.error("io task")
    return "IO bound task finish!"

#simula una tarea CPU con operaciones matemáticas repetitivas
@app.get("/cpu_task")
async def cpu_task():
    for i in range(1000):
        _ = i * i * i
    logging.error("cpu task")
    return "CPU bound task finish!"

#simula códigos de response aleatorios
@app.get("/random_status")
async def random_status(response: Response):
    response.status_code = random.choice([200, 200, 300, 400, 500])
    logging.error("random status")
    return {"path": "/random_status"}

#simula latencias variables entre 0 y 5 segundos
@app.get("/random_sleep")
async def random_sleep(response: Response):
    time.sleep(random.randint(0, 5))
    logging.error("random sleep")
    return {"path": "/random_sleep"}

#simula errores intencionales
@app.get("/error_test")
async def error_test(response: Response):
    logging.error("got error!!!!")
    raise ValueError("value error")

#simula tracing distribuido, haciendo peticiones en app-a, b y c en el mismo trace
@app.get("/chain")
async def chain(response: Response):
    headers = {}
    inject(headers)  
    logging.critical(headers)

    async with httpx.AsyncClient() as client:
        await client.get(
            "http://localhost:8000/",
            headers=headers,
        )
    async with httpx.AsyncClient() as client:
        await client.get(
            f"http://{TARGET_ONE_HOST}:8000/io_task",
            headers=headers,
        )
    async with httpx.AsyncClient() as client:
        await client.get(
            f"http://{TARGET_TWO_HOST}:8000/cpu_task",
            headers=headers,
        )
    logging.info("Chain Finished")
    return {"path": "/chain"}

#ejecuta uvicorn y permite correlación de logs y traces
if __name__ == "__main__":
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"][
        "fmt"
    ] = "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] - %(message)s"
    uvicorn.run(app, host="0.0.0.0", port=EXPOSE_PORT, log_config=log_config)