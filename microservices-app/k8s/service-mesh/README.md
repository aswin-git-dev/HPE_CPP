\# Service Mesh Integration using Linkerd



\## Prerequisites



\- Docker Desktop

\- Kubernetes (Minikube)

\- kubectl

\- Linkerd CLI

\- Git

\- Running microservices cluster





\## Objective



This project integrates Linkerd service mesh with the Kubernetes-based microservices application to provide secure service-to-service communication, automatic mTLS, traffic visibility, and observability.



\## Components Installed



\- Linkerd Control Plane

\- Linkerd Identity

\- Linkerd Destination

\- Linkerd Proxy Injector

\- Linkerd Viz Dashboard



\## Namespaces Injected



Only business microservices are injected:



\- user-ns

\- product-ns

\- order-ns

\- notification-ns



The payment-service is inside order-ns.



\## Why only business services?



We injected only business services first to reduce risk. Infrastructure services like MongoDB, OpenSearch, Grafana, Falco, and Kubernetes system pods were not injected initially to avoid disrupting logging and monitoring.



\## Setup Steps



1\. Start Minikube cluster



```bash

minikube start --nodes 3



2\\. Verify cluster



```bash

kubectl get nodes



3\\. Install Linkerd



```bash

service-mesh/install-linkerd.bat



4\\. Inject business services



```bash

service-mesh/inject-business-services.bat



5\\. Verify installation



```bash

linkerd check

linkerd viz check



\## Verification



\### Before Linkerd Injection



```text

user-service          1/1 Running

product-service       1/1 Running

order-service         1/1 Running

payment-service       1/1 Running

notification-service  1/1 Running

```



\### After Linkerd Injection



```text

user-service          2/2 Running

product-service       2/2 Running

order-service         2/2 Running

payment-service       2/2 Running

notification-service  2/2 Running

```



The additional container is the \*\*Linkerd Sidecar Proxy\*\*, which intercepts and secures all service-to-service communication.



!\[Linkerd Dashboard](screenshots/linkerd-sidecar-injection.png)



\### Commands Used



\#### Install Linkerd



```bat

service-mesh\\install-linkerd.bat

```



\#### Inject Business Services



```bat

service-mesh\\inject-business-services.bat

```



\#### Verify Linkerd Installation



```bat

linkerd check

!\[Linkerd Dashboard](screenshots/linkerd-check.png)



```bat

linkerd viz check



!\[Linkerd Dashboard](screenshots/linkerd-viz-check.png)



kubectl get pods -n linkerd

kubectl get pods -n linkerd-viz

```



\#### View Service Mesh Dashboard



```bat

linkerd viz dashboard

```



\#### View Traffic Statistics



```bat

linkerd viz stat deploy -n user-ns

linkerd viz stat deploy -n product-ns

linkerd viz stat deploy -n order-ns

linkerd viz stat deploy -n notification-ns

```



\### Successfully Integrated Services



\* user-service

\* product-service

\* order-service

\* payment-service

\* notification-service



\### Linkerd Control Plane Components



\* linkerd-identity

\* linkerd-destination

\* linkerd-proxy-injector



\### Linkerd Viz Components



\* metrics-api

\* prometheus

\* tap

\* tap-injector

\* web



!\[Linkerd Dashboard](screenshots/linkerd-observability.png)



\### Benefits Achieved



\* Automatic mTLS between microservices

\* Secure service-to-service communication

\* Traffic monitoring and observability

\* Request success and failure tracking

\* Latency monitoring

\* Foundation for anomaly detection and security analytics



\## Service Mesh Validation



The Linkerd Viz dashboard confirms that business microservices were successfully meshed and are managed by Linkerd.



!\[Linkerd Dashboard](screenshots/linkerd-dashboard.png)



