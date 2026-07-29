package de.royaldownloader.app.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalAmethyst
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalGoldBorder
import de.royaldownloader.app.ui.theme.RoyalGoldBorderStrong
import de.royaldownloader.app.ui.theme.RoyalInk
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalVault

@Composable
fun RoyalSearchField(
    query: String,
    onQueryChange: (String) -> Unit,
    placeholder: String,
    onSearch: () -> Unit,
    clearContentDescription: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = modifier
            .fillMaxWidth()
            .sizeIn(minHeight = 56.dp),
        enabled = enabled,
        textStyle = MaterialTheme.typography.bodyLarge,
        placeholder = {
            Text(
                text = placeholder,
                color = RoyalTextMuted,
                style = MaterialTheme.typography.bodyLarge,
            )
        },
        leadingIcon = {
            Icon(
                imageVector = Icons.Rounded.Search,
                contentDescription = null,
                tint = RoyalGold,
            )
        },
        trailingIcon = if (query.isNotEmpty()) {
            {
                RoyalIconButton(onClick = { onQueryChange("") }) {
                    Icon(
                        imageVector = Icons.Rounded.Close,
                        contentDescription = clearContentDescription,
                    )
                }
            }
        } else {
            null
        },
        singleLine = true,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch() }),
        shape = MaterialTheme.shapes.medium,
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = RoyalText,
            unfocusedTextColor = RoyalText,
            disabledTextColor = RoyalTextMuted.copy(alpha = 0.55f),
            cursorColor = RoyalGold,
            focusedBorderColor = RoyalGoldBorderStrong,
            unfocusedBorderColor = RoyalGoldBorder,
            disabledBorderColor = RoyalGoldBorder.copy(alpha = 0.35f),
            focusedContainerColor = RoyalVault.copy(alpha = 0.90f),
            unfocusedContainerColor = RoyalVault.copy(alpha = 0.68f),
            disabledContainerColor = RoyalAmethyst.copy(alpha = 0.28f),
        ),
    )
}

@Composable
fun RoyalFilterChip(
    selected: Boolean,
    onClick: () -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label) },
        modifier = modifier.sizeIn(minHeight = 40.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.small,
        border = FilterChipDefaults.filterChipBorder(
            enabled = enabled,
            selected = selected,
            borderColor = RoyalGoldBorder,
            selectedBorderColor = RoyalGoldBorderStrong,
        ),
        colors = FilterChipDefaults.filterChipColors(
            containerColor = RoyalAmethyst.copy(alpha = 0.42f),
            labelColor = RoyalTextMuted,
            selectedContainerColor = RoyalGold,
            selectedLabelColor = RoyalInk,
            disabledContainerColor = Color.Transparent,
            disabledLabelColor = RoyalTextMuted.copy(alpha = 0.40f),
        ),
    )
}
