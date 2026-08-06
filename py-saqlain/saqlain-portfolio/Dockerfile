# Use the official .NET runtime
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app

# Use the .NET SDK to build the app
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# FIX: Copy everything from your GitHub first
COPY . .

# FIX: Tell it to look inside the "Portfilio Site" folder for your project
RUN dotnet restore "Portfilio Site/MyPortfolio.csproj"
RUN dotnet publish "Portfilio Site/MyPortfolio.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Run the app
FROM base AS final

# Create a non-root user for Hugging Face security
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# Copy the published app to the new user's home
COPY --from=build --chown=user /app/publish .

# Hugging Face expects port 7860 by default
EXPOSE 7860
ENV ASPNETCORE_URLS=http://+:7860

ENTRYPOINT ["dotnet", "MyPortfolio.dll"]
