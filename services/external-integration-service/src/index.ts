import { createServer } from "node:http";

const serviceName = "external-integration-service";
const port = Number.parseInt(process.env.PORT ?? "3103", 10);

const server = createServer((request, response) => {
  if (request.url === "/health/live" || request.url === "/health/ready") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ service: serviceName, status: "ok" }));
    return;
  }

  response.writeHead(404, { "content-type": "application/json" });
  response.end(JSON.stringify({ service: serviceName, error: "NOT_FOUND" }));
});

server.listen(port, "0.0.0.0", () => {
  console.log(JSON.stringify({ service: serviceName, event: "listening", port }));
});
