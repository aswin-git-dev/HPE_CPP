@echo off
echo Running manual image load to bypass Minikube DNS/EOF errors...
if not exist "C:\Temp" mkdir "C:\Temp"

echo ==============================================
echo Saving images from Host Docker...
echo ==============================================
docker save opensearchproject/opensearch:2.11.0 -o C:\Temp\os.tar
docker save opensearchproject/opensearch-dashboards:2.11.0 -o C:\Temp\osd.tar
docker save grafana/grafana:11.0.0 -o C:\Temp\grafana.tar
docker save mongo:6.0 -o C:\Temp\mongo.tar

echo ==============================================
echo Loading images into Minikube Nodes...
echo ==============================================

for %%N in (minikube minikube-m02 minikube-m03) do (
    echo Loading to %%N...
    docker cp C:\Temp\os.tar %%N:/root/os.tar >nul 2>&1
    docker exec %%N docker load -i /root/os.tar >nul 2>&1

    docker cp C:\Temp\osd.tar %%N:/root/osd.tar >nul 2>&1
    docker exec %%N docker load -i /root/osd.tar >nul 2>&1

    docker cp C:\Temp\grafana.tar %%N:/root/grafana.tar >nul 2>&1
    docker exec %%N docker load -i /root/grafana.tar >nul 2>&1

    docker cp C:\Temp\mongo.tar %%N:/root/mongo.tar >nul 2>&1
    docker exec %%N docker load -i /root/mongo.tar >nul 2>&1
)

echo Cleaning up...
del C:\Temp\os.tar C:\Temp\osd.tar C:\Temp\grafana.tar C:\Temp\mongo.tar
echo Done! Images are securely inside the Minikube cluster nodes.
