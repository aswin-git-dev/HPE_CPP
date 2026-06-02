@echo off
echo Enabling Linkerd injection for business namespaces...

kubectl annotate namespace user-ns linkerd.io/inject=enabled --overwrite
kubectl annotate namespace product-ns linkerd.io/inject=enabled --overwrite
kubectl annotate namespace order-ns linkerd.io/inject=enabled --overwrite
kubectl annotate namespace notification-ns linkerd.io/inject=enabled --overwrite

echo Restarting business services...

kubectl rollout restart deployment user-service -n user-ns
kubectl rollout restart deployment product-service -n product-ns
kubectl rollout restart deployment order-service -n order-ns
kubectl rollout restart deployment payment-service -n order-ns
kubectl rollout restart deployment notification-service -n notification-ns

echo Done. Check pods should show 2/2 Running.
kubectl get pods -n user-ns
kubectl get pods -n product-ns
kubectl get pods -n order-ns
kubectl get pods -n notification-ns