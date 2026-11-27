ARG BUILD_FROM
FROM ${BUILD_FROM}
ARG BUILD_VERSION
ARG BUILD_ARCH
RUN apk add --no-cache python3 py3-pyserial py3-smbus py3-paho-mqtt openssl ca-certificates
COPY base /build/base
COPY build_source.py /build/build_source.py
COPY app/mqtt_bridge.py /app/mqtt_bridge.py
COPY app/hardware_profile.py /app/hardware_profile.py
COPY app/test_lab.py /app/test_lab.py
COPY app/advanced.py /app/advanced.py
COPY run.sh /run.sh
RUN python3 /build/build_source.py /app/pulsar_dali_control.py && python3 -m py_compile /app/*.py && rm -rf /build && chmod a+x /run.sh
LABEL io.hass.version="$BUILD_VERSION" io.hass.type="app" io.hass.arch="$BUILD_ARCH"
CMD [ "/run.sh" ]
