FROM python:3.10-slim

WORKDIR /code

RUN apt-get update && \
    apt-get install -y git hwloc && \
    rm -rf /var/lib/apt/lists/*

COPY setup.py setup.cfg MANIFEST.in ./
COPY fluxbind_dra ./fluxbind_dra

# Install fluxbind from the specific test-cpuset branch.
RUN pip install --no-cache-dir "git+https://github.com/converged-computing/fluxbind.git@test-cpuset"
RUN pip install --no-cache-dir .

ENTRYPOINT ["fluxbind-dra-driver"]
CMD ["serve"]
