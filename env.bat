python -c "import secrets; print(f\"POSTGRES_USER=orion_admin\nPOSTGRES_PASSWORD={secrets.
  token_hex(16)}\nPOSTGRES_DB=orion\nDATABASE_URL=postgresql://orion_admin:pass@postgres:5432/orion\nREDIS_PASSWORD={secrets.
  token_hex(16)}\nNATS_USER=orion_worker\nNATS_PASSWORD={secrets.token_hex(16)}\nKEYCLOAK_ADMIN=admin\nKEYCLOAK_ADMIN_PASSWORD={secrets.
  token_hex(16)}\nKC_DB=postgres\nKC_DB_URL=jdbc:postgresql://postgres:5432/orion\nKC_DB_USERNAME=orion_admin\nKC_DB_PASSWORD=pass\nGF_SECURITY_ADMIN_USE
  R=admin\nGF_SECURITY_ADMIN_PASSWORD={secrets.
  token_hex(16)}\nGF_DATABASE_TYPE=postgres\nGF_DATABASE_HOST=postgres:5432\nGF_DATABASE_NAME=orion\nGF_DATABASE_USER=orion_admin\nGF_DATABASE_PASSWORD=p
  ass\")" > .env
