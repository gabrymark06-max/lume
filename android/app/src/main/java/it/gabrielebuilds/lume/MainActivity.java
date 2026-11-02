package it.gabrielebuilds.lume;

import android.app.Activity;
import android.app.UiModeManager;
import android.content.Intent;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/** Contenitore HTTPS senza SDK ads o bridge JavaScript verso il dispositivo. */
public class MainActivity extends Activity {
    private WebView web;
    private FrameLayout container;
    private View fullscreen;
    private WebChromeClient.CustomViewCallback fullscreenCallback;
    private ValueCallback<Uri[]> fileCallback;
    private boolean tv;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        tv = ((UiModeManager)getSystemService(UI_MODE_SERVICE)).getCurrentModeType() == Configuration.UI_MODE_TYPE_TELEVISION;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (tv) getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        container = new FrameLayout(this);
        web = new WebView(this);
        container.addView(web,new FrameLayout.LayoutParams(-1,-1));
        setContentView(container);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if(tv) settings.setUserAgentString(settings.getUserAgentString()+" LumeTV/0.3");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                Uri uri=request.getUrl();
                if("https".equals(uri.getScheme()) && Uri.parse(BuildConfig.BASE_URL).getHost().equals(uri.getHost())) return false;
                if("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) {
                    try {startActivity(new Intent(Intent.ACTION_VIEW,uri));} catch(Exception ignored) {}
                }
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onShowCustomView(View view,CustomViewCallback callback){
                if(fullscreen!=null){callback.onCustomViewHidden();return;}
                fullscreen=view;fullscreenCallback=callback;web.setVisibility(View.GONE);container.addView(view,new FrameLayout.LayoutParams(-1,-1));
                getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
            }
            @Override public void onHideCustomView(){exitFullscreen();}
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params){
                if(fileCallback!=null)fileCallback.onReceiveValue(null);
                fileCallback=callback;
                Intent picker=new Intent(Intent.ACTION_OPEN_DOCUMENT);picker.addCategory(Intent.CATEGORY_OPENABLE);picker.setType("application/json");
                try{startActivityForResult(picker,10);return true;}catch(Exception ignored){fileCallback=null;return false;}
            }
        });
        if(saved==null)web.loadUrl(BuildConfig.BASE_URL+(tv?"/?tv=1":"/"));else web.restoreState(saved);
    }
    private void exitFullscreen(){
        if(fullscreen==null)return;
        container.removeView(fullscreen);fullscreen=null;web.setVisibility(View.VISIBLE);
        fullscreenCallback.onCustomViewHidden();fullscreenCallback=null;
        if(!tv)getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
    }
    @Override public boolean onKeyDown(int code,KeyEvent event){
        if(code==KeyEvent.KEYCODE_BACK){
            if(fullscreen!=null){exitFullscreen();return true;}
            web.evaluateJavascript("Boolean(window.lumeBack && window.lumeBack())",result->{if(!"true".equals(result))finish();});return true;
        }
        if(code==KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE){web.evaluateJavascript("document.querySelector('#video-play')?.click()",null);return true;}
        return super.onKeyDown(code,event);
    }
    @Override protected void onSaveInstanceState(Bundle state){super.onSaveInstanceState(state);web.saveState(state);}
    @Override protected void onPause(){web.evaluateJavascript("document.querySelector('#video')?.pause()",null);CookieManager.getInstance().flush();super.onPause();}
    @Override protected void onDestroy(){if(web!=null)web.destroy();super.onDestroy();}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request==10&&fileCallback!=null){fileCallback.onReceiveValue(result==RESULT_OK&&data!=null?new Uri[]{data.getData()}:null);fileCallback=null;}
    }
}
