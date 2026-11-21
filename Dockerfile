FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ADD https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz /tmp/sqlglot.tgz
RUN mkdir -p /opt/sqlglot && tar xzf /tmp/sqlglot.tgz -C /opt/sqlglot --strip-components=1 && rm /tmp/sqlglot.tgz && chmod -R a+rX /opt/sqlglot
COPY br /app/br
COPY maps /app/maps
COPY selector.py /app/selector.py
RUN chmod -R a+rX /app && python -m compileall -q /app
ENV SQLGLOT_ROOT=/opt/sqlglot
CMD ["python", "-S", "/app/selector.py"]
