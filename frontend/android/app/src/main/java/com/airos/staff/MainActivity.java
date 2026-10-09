package com.airos.staff;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(AppUpdatePlugin.class);
        registerPlugin(LocationTrackerPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
