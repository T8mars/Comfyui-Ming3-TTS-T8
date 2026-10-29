// T8 native CUDA inference kernels. No dependency on PyTorch's C++ ABI.
#include <cuda_runtime.h>
#include <cuda_bf16.h>
#include <stdint.h>
#include <math.h>

#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif

template<class T> __device__ float get(const T* p, int64_t i) { return (float)p[i]; }
template<> __device__ float get(const __nv_bfloat16* p, int64_t i) { return __bfloat162float(p[i]); }
template<class T> __device__ T put(float x) { return (T)x; }
template<> __device__ __nv_bfloat16 put(float x) { return __float2bfloat16_rn(x); }

template<class T, class G, int K=128>
__global__ void kda_kernel(const T* q, const T* k, const T* v, const G* g,
                           const float* beta, const float* A, const float* bias,
                           const float* initial, T* out, float* final_state,
                           int Tn, int H, int V, float scale, float lower,
                           int normalize, int gate, int bounded) {
    int bh = blockIdx.x, b=bh/H, h=bh%H, lane=threadIdx.x;
    int column=blockIdx.y*32+lane;
    __shared__ float qs[K], ks[K], decay[K], qnorm, knorm;
    float state[K];
    #pragma unroll
    for(int i=0;i<K;i++) state[i] = (initial && column<V) ? initial[((int64_t)bh*K+i)*V+column] : 0.f;
    for(int t=0;t<Tn;t++) {
        int64_t offset=((int64_t)b*Tn+t)*H*K+h*K;
        float qq=0.f, kk=0.f;
        for(int i=lane;i<K;i+=32) {
            float qi=get(q,offset+i), ki=get(k,offset+i);
            qs[i]=qi; ks[i]=ki; qq+=qi*qi; kk+=ki*ki;
            float gg=get(g,offset+i);
            if(gate) {
                if(bias) gg+=bias[h*K+i];
                float aa=expf(A[h]);
                gg=bounded ? lower/(1.f+expf(-gg*aa)) : -aa*log1pf(expf(gg));
            }
            decay[i]=expf(gg);
        }
        for(int delta=16;delta;delta/=2) {qq+=__shfl_down_sync(0xffffffff,qq,delta);kk+=__shfl_down_sync(0xffffffff,kk,delta);}
        if(lane==0) {qnorm=normalize ? rsqrtf(qq+1e-6f) : 1.f;knorm=normalize ? rsqrtf(kk+1e-6f) : 1.f;}
        __syncwarp();
        for(int i=lane;i<K;i+=32) {qs[i]*=qnorm*scale;ks[i]*=knorm;}
        __syncwarp();
        if(column<V) {
            float dot=0.f;
            #pragma unroll
            for(int i=0;i<K;i++) {state[i]*=decay[i];dot+=state[i]*ks[i];}
            float residual=get(v,((int64_t)b*Tn+t)*H*V+h*V+column)-dot;
            float bt=beta[((int64_t)b*Tn+t)*H+h], result=0.f;
            #pragma unroll
            for(int i=0;i<K;i++) {state[i]+=(ks[i]*bt)*residual;result+=state[i]*qs[i];}
            out[((int64_t)b*Tn+t)*H*V+h*V+column]=put<T>(result);
        }
        __syncwarp();
    }
    if(column<V) {
        #pragma unroll
        for(int i=0;i<K;i++) final_state[((int64_t)bh*K+i)*V+column]=state[i];
    }
}

API int ming_kda(const void* q,const void* k,const void* v,const void* g,const float* beta,
                 const float* A,const float* bias,const float* initial,void* out,float* final_state,
                 int B,int Tn,int H,int K,int V,int bf16,int gate_bf16,float scale,float lower,
                 int normalize,int gate,int bounded,uintptr_t stream) {
    if(K!=128 || V<1 || V>256 || !q || !k || !v || !g || !beta || (gate&&!A)) return (int)cudaErrorInvalidValue;
    dim3 grid(B*H,(V+31)/32);
    cudaStream_t s=(cudaStream_t)stream;
    #define RUN(T,G) kda_kernel<T,G><<<grid,32,0,s>>>((const T*)q,(const T*)k,(const T*)v,(const G*)g,beta,A,bias,initial,(T*)out,final_state,Tn,H,V,scale,lower,normalize,gate,bounded)
    if(bf16) {if(gate_bf16) {RUN(__nv_bfloat16,__nv_bfloat16);} else {RUN(__nv_bfloat16,float);}}
    else {if(gate_bf16) {RUN(float,__nv_bfloat16);} else {RUN(float,float);}}
    #undef RUN
    return (int)cudaGetLastError();
}

template<class S>
__global__ void expert_gemv(const __nv_bfloat16* x,const int64_t* ids,const int8_t* w,
                           const S* scales,__nv_bfloat16* y,int pairs,int repeats,int N,int K) {
    int pair=blockIdx.y, row=blockIdx.x*4+threadIdx.x/32, lane=threadIdx.x%32;
    if(row>=N) return;
    int64_t expert=ids[pair];
    float scale=get(scales,expert*N+row), value=0.f;
    int64_t weight=(expert*N+row)*K, input=(int64_t)(pair/repeats)*K;
    for(int col=lane;col<K;col+=32) {
        // Match the portable path's BF16 materialization before accumulation.
        float restored=__bfloat162float(__float2bfloat16_rn((float)w[weight+col]*scale));
        value+=get(x,input+col)*restored;
    }
    for(int delta=16;delta;delta/=2) value+=__shfl_down_sync(0xffffffff,value,delta);
    if(lane==0) y[(int64_t)pair*N+row]=__float2bfloat16_rn(value);
}

API int ming_expert(const void* x,const int64_t* ids,const int8_t* w,const void* scales,void* y,
                    int pairs,int repeats,int N,int K,int scale_bf16,uintptr_t stream) {
    dim3 grid((N+3)/4,pairs);
    if(scale_bf16) expert_gemv<<<grid,128,0,(cudaStream_t)stream>>>((const __nv_bfloat16*)x,ids,w,(const __nv_bfloat16*)scales,(__nv_bfloat16*)y,pairs,repeats,N,K);
    else expert_gemv<<<grid,128,0,(cudaStream_t)stream>>>((const __nv_bfloat16*)x,ids,w,(const float*)scales,(__nv_bfloat16*)y,pairs,repeats,N,K);
    return (int)cudaGetLastError();
}

API const char* ming_cuda_error(int code) {return cudaGetErrorString((cudaError_t)code);}
API int ming_kernel_version() {return 1;}
