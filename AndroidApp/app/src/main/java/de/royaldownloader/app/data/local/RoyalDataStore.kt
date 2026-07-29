package de.royaldownloader.app.data.local

import android.content.Context
import androidx.datastore.preferences.preferencesDataStore

internal val Context.royalDataStore by preferencesDataStore(name = "royal_downloader")
