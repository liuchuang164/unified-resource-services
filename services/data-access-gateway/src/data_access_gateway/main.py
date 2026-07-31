import uvicorn


def main() -> None:
    uvicorn.run("data_access_gateway.app:app", host="0.0.0.0", port=8081)  # noqa: S104


if __name__ == "__main__":
    main()
