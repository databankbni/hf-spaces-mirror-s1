# Use the official .NET SDK image to build the app
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Since Dockerfile is right next to the csproj, copy and restore directly
COPY *.csproj ./
RUN dotnet restore

# Copy the rest of the project files and compile
COPY . ./
RUN dotnet publish -c Release -o /app/publish /p:UseAppHost=false

# Build the runtime container image
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .

# Hugging Face deployment environment configurations
ENV ASPNETCORE_URLS=http://+:7860
EXPOSE 7860

# Execute the true compiled web application assembly
ENTRYPOINT ["dotnet", "MyPortfolio.dll"]