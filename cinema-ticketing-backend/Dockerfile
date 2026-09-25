FROM eclipse-temurin:21-jre

WORKDIR /app
# Screening times and business deadlines use the cinema's local wall clock.
ENV JAVA_TOOL_OPTIONS="-Duser.timezone=Asia/Shanghai"
COPY target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
